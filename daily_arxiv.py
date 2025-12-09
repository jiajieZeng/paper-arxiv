import datetime as dt
import requests
import json
import arxiv
import os
from arxiv import UnexpectedEmptyPageError
import matplotlib.pyplot as plt
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime




base_url = "https://arxiv.paperswithcode.com/api/v0/papers/"
github_url = "https://api.github.com/search/repositories"
arxiv_url = "http://arxiv.org/"

BASE_URL = "https://arxiv.paperswithcode.com/api/v0/papers/"

KEEP   = {"cs.CL", "cs.SE", "cs.AI", "cs.LG", "cs.NE", "cs.PL"}
BLOCKS = {"eess.AS", "cs.SD", "eess.SP", "q-bio.BM"}


def get_authors(authors, first_author=False):
    output = str()
    if first_author == False:
        output = ", ".join(str(author) for author in authors)
    else:
        output = authors[0]
    return output
def make_collapsible(text: str, title: str = "Full Abstract") -> str:
    text = text.replace("|", "\\|")      
    return f"<details><summary>{title}</summary>{text}</details>"

def get_label(categories):
    output = str()
    if len(categories) != 1:  
        output = ", ".join(str(c) for c in categories)
    else:
        output = categories[0]
    return output


def sort_papers(papers):
    output = dict()
    keys = list(papers.keys())
    keys.sort(reverse=True)
    for key in keys:
        output[key] = papers[key]
    return output

def iter_results_safe(client, search):
    gen = client.results(search)
    while True:
        try:
            yield next(gen)
        except UnexpectedEmptyPageError as e:
            print(f"[arXiv] empty page, stop paging: {e}")
            break
        except StopIteration:
            break

def get_daily_papers(topic, query, max_results=200):
    """
    抓取 arXiv + PapersWithCode 信息并按 markdown 表格行返回
    """
    content: dict[str, str] = {}

    # 1. arxiv client
    client = arxiv.Client(
        page_size=20,    
        delay_seconds=10,  
        num_retries=10    
    )

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )

    # 2. iter_results
    for res in iter_results_safe(client, search):

        cats = res.categories                 # e.g. ['cs.CL', 'cs.LG']
        if not any(c in KEEP for c in cats):
            continue
        if any(c in cats for c in BLOCKS):
            continue  
                           

        paper_id_full  = res.get_short_id()  
        paper_id       = paper_id_full.split("v")[0]  
        update_time    = res.updated.date()
        paper_title    = res.title
        paper_url      = res.entry_id
        paper_abstract = res.summary.replace("\n", " ")
        collapsed_abs = make_collapsible(paper_abstract)      
        paper_labels   = ", ".join(cats)

        repo_url = "null"
        try:
            r = requests.get(BASE_URL + paper_id_full, timeout=10).json()
            if r.get("official"):
                repo_url = r["official"]["url"]
        except Exception as e:
             pass

        md_row = (
            f"|**{update_time}**|**{paper_title}**|{paper_labels}| "
            f"{collapsed_abs}|[{paper_id_full}]({paper_url})| "
        )
        md_row += f"**[code]({repo_url})**|" if repo_url != "null" else "null|"

        content[paper_id] = md_row

    return {topic: content}


def make_collapsible(text: str, title: str = "Full Abstract") -> str:
    text = text.replace("|", "\\|")      
    return f"<details><summary>{title}</summary>{text}</details>"

def wrap_old_row(md_row: str) -> str:
    if "<details" in md_row:
        return md_row

    newline = "\n" if md_row.endswith("\n") else ""
    row = md_row.rstrip("\n")  
    cells = row.split("|")
    if len(cells) < 8:         
        return md_row

    cells[4] = make_collapsible(cells[4].strip())

    return "|".join(cells) + newline

def update_json_file(filename, data_all):
    # 1. 如果文件存在，读取旧数据
    if os.path.exists(filename):
        with open(filename, "r", encoding='utf-8') as f:
            content = f.read().strip()
            # 如果文件为空，初始化为 {}
            json_data = json.loads(content) if content else {}
    else:
        # 2. 如果文件不存在，直接初始化为空字典
        json_data = {}

    # 3. 兼容处理：给旧数据加上折叠格式
    for kw in json_data.values():
        for pid in list(kw.keys()):
            kw[pid] = wrap_old_row(kw[pid])

    # 4. 合并新抓取的数据
    for data in data_all:
        for keyword, papers in data.items():
            if not papers: continue # 如果没抓到数据跳过
            json_data.setdefault(keyword, {}).update(papers)

    # 5. 写入文件（确保目录存在）
    # 获取目录路径 (docs)
    directory = os.path.dirname(filename)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    with open(filename, "w", encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    

def json_to_md(filename, 
               to_web=False,
               use_title=True,
               use_tc=True,
               show_badge=True):
    """
    @param filename: str
    @param md_filename: str
    @return None
    """

    DateNow = str(dt.date.today()).replace('-', '.')

    with open(filename, "r", encoding='utf-8') as f:
        data = json.loads(f.read())

    # 1. 为每个 Topic 生成单独的 MD 文件
    generated_files = []
    for topic, papers in data.items():
        if not papers: continue
        
        # 文件名：Code Generation.md
        topic_filename = f"{topic}.md"
        generated_files.append(topic_filename)

        with open(topic_filename, "w+", encoding='utf-8') as f:
            f.write(f"# {topic}\n\n")
            f.write(f"> Updated on {DateNow}\n\n")
            f.write(f"[🔙 Back to Index](README.md)\n\n") # 返回主页的链接
            
            f.write("| Date | Title | Categories | Abstract | PDF | Code |\n")
            f.write("|:---|:---|:---|:---|:---|:---|\n")

            sorted_papers = sort_papers(papers)
            for _, v in sorted_papers.items():
                f.write(v.rstrip("\n") + "\n")
            
            f.write(f"\n<p align=right>(<a href='#{topic.lower().replace(' ', '-')}'>back to top</a>)</p>\n")
        
        

    # 2. 生成主 README.md (作为索引)
    with open("README.md", "w+", encoding='utf-8') as f:
        f.write(f"# Daily ArXiv Papers\n\n")
        f.write(f"> Last Updated: {DateNow}\n\n")
        
        # 显示趋势图
        if os.path.exists("imgs/trend.png"):
            f.write("![Monthly Trend](imgs/trend.png)\n\n")

        f.write("## Topic List\n\n")
        f.write("Click to view papers:\n\n")
        
        # 写入目录链接
        for topic in data.keys():
            # 这里必须确保文件名和上面生成的一致
            f.write(f"- [**{topic}**]({topic}.md)\n")
    
    

def json_to_trend(json_file: str | Path, img_file: str | Path) -> None:
    json_file = Path(json_file).expanduser().resolve()
    img_file  = Path(img_file).expanduser().resolve()

    with json_file.open("r", encoding="utf‑8") as f:
        data = json.load(f)

    counts = Counter()
    for topic_dict in data.values():
        for arxiv_id in topic_dict.keys():
            yymm = arxiv_id[:4]
            year  = 2000 + int(yymm[:2])
            month = int(yymm[2:])
            ym_key = f"{year:04d}-{month:02d}"
            counts[ym_key] += 1

    if not counts:
        print("no data")
        return

    ym_dates = {datetime.strptime(k, "%Y-%m"): k for k in counts}
    sorted_keys = [ym_dates[d] for d in sorted(ym_dates)]
    values = [counts[k] for k in sorted_keys]
    idx_map = {k: i for i, k in enumerate(sorted_keys)}

    year_tot, year_months = defaultdict(int), defaultdict(int)
    for k, v in counts.items():
        y = k[:4]
        year_tot[y]   += v
        year_months[y] += 1
    year_avg = {y: year_tot[y] / year_months[y] for y in year_tot}

    year_span = defaultdict(list)
    for k in sorted_keys:
        year_span[k[:4]].append(idx_map[k])

    plt.figure(figsize=(9, 4))
    plt.plot(sorted_keys, values, marker="o", linewidth=1, label="Monthly count")

    first_bar = True
    for y, avg in year_avg.items():
        xs = year_span[y]
        xmin, xmax = min(xs), max(xs)
        bar_x = (xmin + xmax) / 2
        bar_w = (xmax - xmin + 1) * 0.8    
        plt.bar(bar_x, avg,
                width=bar_w,
                color="C1",
                alpha=0.2,
                label=f"Anual avg" if first_bar else None)
        first_bar = False 

    plt.title("ArXiv Papers per Month")
    # plt.xlabel("Month")
    plt.ylabel("Count")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.xticks(rotation=45, ha="right")
    plt.legend()

    img_file.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(img_file, dpi=300)
    plt.close()
    print(f"✅ trend save in: {img_file}")


if __name__ == "__main__":

    # ================= 新增代码开始 =================
    # 获取当前脚本文件所在的绝对路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 强制将工作目录切换到脚本所在目录
    os.chdir(script_dir)
    print(f"Working Directory set to: {script_dir}")
    # ================= 新增代码结束 =================

    os.makedirs("docs", exist_ok=True)
    os.makedirs("imgs", exist_ok=True)

    data_collector = []

    # my keyword
    keywords = dict()
    
    # keywords["GUI_Testing"] = 'all:"GUI testing" OR (all:"GUI" AND all:"testing")'
    # keywords["MA-LLM"] = '(all:"multi-agent" AND all:"LLM") OR all:"Multi-Agent"'
    keywords["MA-CoEvo"] = '(all:"co-evolution" OR all:"co-evolving" OR all:"collaborative evolution") AND (all:"agent" OR all:"multi-agent" OR all:"dual-agent" OR all:"LLM")'
    keywords["MA-CoEvo-RL"] = '(abs:"co-evolution" OR abs:"co-evolving") AND (abs:"multi-agent" OR abs:"dual-agent") AND (abs:"reinforcement learning" OR abs:"RL" OR abs:"PPO")'
    keywords["CodeGeneration_LLM"] = '(all:"code generation" OR all:"program synthesis" OR all:"text-to-code") AND (all:"LLM" OR all:"Large Language Model")'
    keywords["GUI_LLM_RL_MA"] = '(abs:"GUI testing" OR abs:"Android testing" OR abs:"mobile app testing") AND (abs:"LLM" OR abs:"Large Language Model" OR abs:"Agent") AND (abs:"reinforcement learning" OR abs:"multi-agent" OR abs:"co-evolution" OR abs:"evolutionary")'
    for topic, keyword in keywords.items():
        print("Keyword: " + topic)

        data = get_daily_papers(topic, query=keyword, max_results=50)
        data_collector.append(data)

        print("\n")

    json_file = "docs/arxiv-daily.json"
    # img_file = "imgs/trend.png"
    

    update_json_file(json_file, data_collector)
    # json_to_trend(json_file, img_file)
    json_to_md(json_file)

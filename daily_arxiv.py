import datetime as dt
import requests
import json
import arxiv
import os
import re
from arxiv import UnexpectedEmptyPageError

# ================= 关键修改：服务器端绘图配置 =================
import matplotlib
matplotlib.use('Agg')  # 强制使用非交互式后端，防止弹窗报错
import matplotlib.pyplot as plt
# ==========================================================

from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

# ================= 配置区域 =================
base_url = "https://arxiv.paperswithcode.com/api/v0/papers/"
github_url = "https://api.github.com/search/repositories"
arxiv_url = "http://arxiv.org/"
BASE_URL = "https://arxiv.paperswithcode.com/api/v0/papers/"

KEEP   = {"cs.CL", "cs.SE", "cs.AI", "cs.LG", "cs.NE", "cs.PL"}
BLOCKS = {"eess.AS", "cs.SD", "eess.SP", "q-bio.BM"}
# ===========================================

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
        cats = res.categories                 
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
    if os.path.exists(filename):
        with open(filename, "r", encoding='utf-8') as f:
            content = f.read().strip()
            json_data = json.loads(content) if content else {}
    else:
        json_data = {}

    for kw in json_data.values():
        for pid in list(kw.keys()):
            kw[pid] = wrap_old_row(kw[pid])

    for data in data_all:
        for keyword, papers in data.items():
            if not papers: continue
            json_data.setdefault(keyword, {}).update(papers)

    directory = os.path.dirname(filename)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    with open(filename, "w", encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

def sanitize_filename(name: str) -> str:
    """将 Topic 名称转换为安全的文件名 (去除空格和特殊符号)"""
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', name)

def draw_trend_figure(paper_dict: dict, title: str, save_path: Path):
    """
    绘制单个 Topic 的趋势图
    """
    counts = Counter()
    for arxiv_id in paper_dict.keys():
        if "." in arxiv_id:
            yymm = arxiv_id.split(".")[0] # e.g. 2312
        else:
            continue 
        
        if len(yymm) != 4: continue

        year  = 2000 + int(yymm[:2])
        month = int(yymm[2:])
        ym_key = f"{year:04d}-{month:02d}"
        counts[ym_key] += 1

    if not counts:
        print(f"No valid data to plot for {title}")
        return

    ym_dates = {datetime.strptime(k, "%Y-%m"): k for k in counts}
    sorted_keys = [ym_dates[d] for d in sorted(ym_dates)]
    values = [counts[k] for k in sorted_keys]
    
    year_tot, year_months = defaultdict(int), defaultdict(int)
    for k, v in counts.items():
        y = k[:4]
        year_tot[y]   += v
        year_months[y] += 1
    year_avg = {y: year_tot[y] / year_months[y] for y in year_tot}

    plt.figure(figsize=(9, 4))
    
    plt.plot(sorted_keys, values, marker="o", linewidth=1, label="Monthly count")

    idx_map = {k: i for i, k in enumerate(sorted_keys)}
    year_span = defaultdict(list)
    for k in sorted_keys:
        year_span[k[:4]].append(idx_map[k])

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

    plt.title(f"ArXiv Trend: {title}")
    plt.ylabel("Count")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.xticks(rotation=45, ha="right")
    plt.legend()
    plt.tight_layout()
    
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"✅ Trend saved: {save_path}")

def generate_all_trends(json_file: str, img_dir: str = "imgs"):
    """
    读取 JSON，为每个 Topic 生成一张图
    """
    json_path = Path(json_file).expanduser().resolve()
    img_dir_path = Path(img_dir)
    img_dir_path.mkdir(exist_ok=True)

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    for topic, papers in data.items():
        if not papers: continue
        
        safe_name = sanitize_filename(topic)
        save_path = img_dir_path / f"trend_{safe_name}.png"
        
        draw_trend_figure(papers, topic, save_path)

def json_to_md(filename, to_web=False):
    """
    生成 README.md 和 各个 Topic 的 MD 文件
    """
    DateNow = str(dt.date.today()).replace('-', '.')

    with open(filename, "r", encoding='utf-8') as f:
        data = json.loads(f.read())

    # 1. 为每个 Topic 生成单独的 MD 文件 (详细列表)
    for topic, papers in data.items():
        if not papers: continue
        
        topic_filename = f"{topic}.md"
        
        with open(topic_filename, "w+", encoding='utf-8') as f:
            f.write(f"# {topic}\n\n")
            f.write(f"> Updated on {DateNow}\n\n")
            f.write(f"[🔙 Back to Index](README.md)\n\n")
            
            # 在子页面也展示趋势图
            safe_name = sanitize_filename(topic)
            img_path = f"imgs/trend_{safe_name}.png"
            if os.path.exists(img_path):
                 f.write(f"![Trend]({img_path})\n\n")

            f.write("| Date | Title | Categories | Abstract | PDF | Code |\n")
            f.write("|:---|:---|:---|:---|:---|:---|\n")

            sorted_papers = sort_papers(papers)
            for _, v in sorted_papers.items():
                f.write(v.rstrip("\n") + "\n")
            
            f.write(f"\n<p align=right>(<a href='#{sanitize_filename(topic).lower()}'>back to top</a>)</p>\n")
        

    # 2. 生成主 README.md (作为索引 + 展示所有趋势图)
    with open("README.md", "w+", encoding='utf-8') as f:
        f.write(f"# Daily ArXiv Papers\n\n")
        f.write(f"> Last Updated: {DateNow}\n\n")
        
        # === 简介部分 (按照你的要求修改) ===
        f.write("This project provides daily updates on ArXiv papers regarding Multi-Agent LLMs, GUI Testing, and Code Generation. It builds upon the work of @bansky-cl, with refinements by @bbc00710086, and is currently deployed and maintained by zzz.\n\n")
        # =================================
        
        f.write("## Topic Trends & Lists\n\n")
        
        # 遍历所有 Topic，直接展示 图片 + 链接
        for topic in data.keys():
            safe_name = sanitize_filename(topic)
            img_path = f"imgs/trend_{safe_name}.png"
            detail_md = f"{topic}.md"

            f.write(f"### {topic}\n")
            
            # 插入趋势图
            if os.path.exists(img_path):
                f.write(f"![{topic} Trend]({img_path})\n\n")
            else:
                f.write("> (No trend data available)\n\n")

            # 插入跳转链接
            f.write(f"👉 [**View Paper List for {topic}**]({detail_md})\n\n")
            f.write("---\n") # 分割线

if __name__ == "__main__":

    # ================= 路径定位 (兼容 Crontab) =================
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    print(f"Working Directory set to: {script_dir}")
    # ========================================================

    os.makedirs("docs", exist_ok=True)
    os.makedirs("imgs", exist_ok=True)

    data_collector = []
    keywords = dict()
    
    # ================= 你的关键词配置 =================
    keywords["MA-CoEvo"] = '(all:"co-evolution" OR all:"co-evolving" OR all:"collaborative evolution") AND (all:"agent" OR all:"multi-agent" OR all:"dual-agent" OR all:"LLM")'
    keywords["MA-CoEvo-RL"] = '(abs:"co-evolution" OR abs:"co-evolving") AND (abs:"multi-agent" OR abs:"dual-agent") AND (abs:"reinforcement learning" OR abs:"RL" OR abs:"PPO")'
    keywords["CodeGeneration_LLM"] = '(all:"code generation" OR all:"program synthesis" OR all:"text-to-code") AND (all:"LLM" OR all:"Large Language Model")'
    keywords["GUI_LLM_RL_MA"] = '(abs:"GUI testing" OR abs:"Android testing" OR abs:"mobile app testing") AND (abs:"LLM" OR abs:"Large Language Model" OR abs:"Agent") AND (abs:"reinforcement learning" OR abs:"multi-agent" OR abs:"co-evolution" OR abs:"evolutionary")'
    # ===============================================

    for topic, keyword in keywords.items():
        print("Keyword: " + topic)
        # 获取数据
        data = get_daily_papers(topic, query=keyword, max_results=50)
        data_collector.append(data)
        print("\n")

    json_file = "docs/arxiv-daily.json"
    
    # 1. 更新数据文件
    update_json_file(json_file, data_collector)
    
    # 2. 生成所有 Topic 的趋势图
    generate_all_trends(json_file, "imgs")
    
    # 3. 生成 Markdown (包含图片和简介)
    json_to_md(json_file)

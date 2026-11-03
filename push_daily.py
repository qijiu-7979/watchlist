# -*- coding: utf-8 -*-
"""
本地每日推送：生成最新看板 index.html 并 push 到 GitHub（GitHub Pages 固定网址展示）。
每天由本地自动化任务调用；neodata token 从本机缓存读取（本机每日可刷新）。
"""
import os, json, subprocess, datetime, sys
sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE = r"C:\Users\jianmin.huang\.workbuddy\plugins\marketplaces\cb_teams_marketplace\plugins\finance-data\skills\.neodata_token"

def main():
    # 1) 注入本机当日 token
    try:
        tok = json.load(open(TOKEN_CACHE, encoding='utf-8'))
        os.environ['NEODATA_TOKEN'] = tok['token'] if isinstance(tok, dict) else tok
    except Exception as e:
        print('token 读取失败:', e); return
    # 2) 生成看板
    import generate_static
    generate_static.main()
    # 3) git 提交并推送
    def run(cmd):
        r = subprocess.run(cmd, cwd=HERE, shell=True, capture_output=True, text=True)
        print(cmd, '=>', (r.stdout + r.stderr).strip()[:300])
    today = datetime.date.today().isoformat()
    run('git add index.html watchlist.json')
    run(f'git commit -m "chore: 每日更新 {today}"')
    run('git push')

if __name__ == '__main__':
    main()

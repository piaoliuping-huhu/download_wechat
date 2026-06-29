import re, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('_test_us_stocks.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Find article links in topic page
article_links = re.findall(r'/articles/([^/]+/\d{4}-\d{2}-\d{2})', html)
print(f"=== Article links: {len(set(article_links))} ===")
for l in sorted(set(article_links))[:10]:
    print(f"  /articles/{l}")

# Find total pages
pages = re.findall(r'共 (\d+) 页', html)
total = re.findall(r'总计 (\d+) 篇', html)
print(f"\nTotal pages: {pages}, Total articles: {total}")

# Find current page
curr = re.findall(r'当前第 (\d+)', html)
print(f"Current page: {curr}")

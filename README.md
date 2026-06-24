# NIKIUID-calendar

无限暖暖「版本内容一览」图片自动抓取仓库。

## 工作原理

GitHub Actions 每天北京时间 10:00 自动运行爬虫,从[官网新闻](https://infinitynikki.nuanpaper.com/news)抓取"版本内容一览"类新闻的正文图片(活动日历/新套装/新玩法等),按版本号分目录存储。

## 目录结构

```
manifest.json        — 版本元数据清单(插件拉取用)
images/
  2.7/               — 按版本号分目录
    00_xxx.png       — 活动日历
    01_xxx.png       — 新套装
    02_xxx.png       — 新玩法
  2.6/
    ...
```

## manifest.json 结构

```json
{
  "updated_at": "2026-06-24T10:00:00+0800",
  "latest_version": "2.7",
  "versions": [
    {
      "version": "2.7",
      "title": "《无限暖暖》2.7版本...",
      "publish_date": "2026-06-22",
      "news_url": "https://infinitynikki.nuanpaper.com/news/912",
      "images": [
        {"filename": "00_xxx.png", "url": "...", "index": 0}
      ]
    }
  ]
}
```

## 手动触发

在 GitHub 仓库的 Actions 页面 → "爬取版本内容一览" → Run workflow。

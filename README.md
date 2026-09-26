# geektime-cli

极客时间课程命令行工具，支持浏览器登录、查询课程与文章、下载已购课程，以及将已下载内容导出为 Markdown 或 PDF。

## 安装

需要 Python 3.10+、Google Chrome。下载视频还需要 `ffmpeg`。PDF 导出依赖 WeasyPrint 的系统库，详见 [WeasyPrint 安装说明](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation)。

```shell
uv tool install geektime-cli
geektime --help
```

也可以在虚拟环境中执行 `python -m pip install geektime-cli`。从源码安装时，在项目根目录执行 `uv tool install .`。

## 登录

```shell
geektime login
geektime login --check
```

登录会打开 Chrome。请在浏览器中手动完成登录。凭据保存到用户配置目录，不写入项目目录；请勿提交配置、缓存或下载内容。

## 查询

```shell
geektime course list
geektime course list --scope all --type c1,c3
geektime course info 100001 --type c1
geektime course chapters 100001
geektime article detail 830657
geektime course list --json
geektime article detail 830657 --raw
```

`--json` 和 `--raw` 不能同时使用。查询优先获取远端数据；网络错误或服务端 5xx 时，已有缓存可用于回退。登录失效会明确报错。

课程分类：`c1` 专栏、`c3` 视频课、`p` 公开课、`d` 每日一课、`q` 大厂案例课。

## 下载与导出

```shell
geektime download --type c1 --text-only
geektime download --limit 3 --output-dir ~/Downloads/GeekTime
geektime export markdown --course "课程名称" --download-dir ~/Downloads/GeekTime
geektime export pdf --course "课程名称" --download-dir ~/Downloads/GeekTime
geektime config show
```

仅下载和使用你有权访问的内容，并遵守极客时间的服务条款。项目不附带任何课程内容或账户凭据。

## 开发

```shell
python -m pip install -e '.[dev]'
python -m pytest -q
```

## 许可证

BSD 3-Clause，见 [LICENSE](LICENSE)。

"""Topic matching for local task and activity rules."""

import re


_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "continue", "complete",
    "develop", "development", "project", "other", "file", "main", "readme",
    "test", "tests", "code", "visual", "studio", "document", "word", "window",
    "windows", "write", "writing", "edit", "editing", "read", "reading", "review",
    "research", "implement", "implementation", "tutorial", "documentation", "docs",
    "report", "pdf", "doc", "docx", "html", "python", "javascript",
}
_CHINESE_STOP = re.compile("继续|完成|当前|目标|下一步|任务|项目|开发|编写|撰写|编辑|修改|处理|实现|阅读|查阅|查找|资料|文档|内容|窗口")


def topic_tokens(value: str) -> set[str]:
    """Find content words and Chinese bigrams that can link two descriptions."""
    value = value.casefold()
    tokens = {word for word in re.findall(r"[a-z][a-z0-9_]{2,}", value) if word not in _STOPWORDS}
    for run in re.findall(r"[\u3400-\u9fff]+", _CHINESE_STOP.sub(" ", value)):
        tokens.update(run[index:index + 2] for index in range(len(run) - 1))
    return tokens

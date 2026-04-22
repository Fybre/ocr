from ..ocr.base import PageResult


class OCRFormatter:
    def format(self, results: list[PageResult], output_format: str) -> str:
        if not results:
            return ""

        if len(results) == 1:
            return results[0].text

        if output_format == "markdown":
            parts = []
            for r in results:
                parts.append(f"## Page {r.page_num}\n\n{r.text}")
            return "\n\n---\n\n".join(parts)

        # plain
        parts = []
        for r in results:
            parts.append(f"--- Page {r.page_num} ---\n\n{r.text}")
        return "\n\n".join(parts)

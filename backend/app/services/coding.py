"""
元认知编码服务 —— 批量分析、评分计算
（预留扩展：RAG、Few-shot 示例库、多模态分析）
"""


class CodingService:
    """元认知编码服务"""

    @staticmethod
    def calculate_dimension_scores(segments: list[dict]) -> dict:
        """从编码片段聚合各维度得分"""
        dim_scores: dict[str, list[int]] = {}
        for seg in segments:
            dim = seg.get("dimension")
            score = seg.get("score")
            if dim and score is not None:
                dim_scores.setdefault(dim, []).append(score)

        result = {}
        for dim, scores in dim_scores.items():
            result[dim] = {
                "average": sum(scores) / len(scores),
                "count": len(scores),
                "scores": scores,
            }
        return result

    @staticmethod
    def determine_level(overall_score: float) -> str:
        """根据综合得分判定等级"""
        if overall_score >= 80:
            return "优秀"
        elif overall_score >= 65:
            return "良好"
        elif overall_score >= 45:
            return "发展中"
        else:
            return "起步"


coding_service = CodingService()

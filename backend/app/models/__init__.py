from app.database import Base

# 导入所有模型，确保 Base.metadata 包含全部表
from app.models.user import User
from app.models.task import AssessmentTask, QuestionPath
from app.models.scale import ScaleDimensionGroup, ScaleItem
from app.models.session import (
    AssessmentSession, DialogueTurn, CodedSegment,
    AudioChunk, TranscriptSegment, InteractionEvent,
)
from app.models.report import (
    MetacognitiveProfile, MetacognitionMeasurement, MeasurementCorrection,
    LearningSuggestion, ConsistencyReport,
)
from app.models.protocol import AssessmentRun, QuestionnaireResponse, TaskOrderAssignment
from app.models.notification import Notification
from app.models.system_config import SystemConfig, SystemConfigHistory
from app.models.asr import AsrJob, TranscriptVersion
from app.models.extraction import ExtractionJob, ExtractionCandidate, ExtractionCandidateRevision
from app.models.narration import NarrationAsset
from app.models.research import (
    MethodTemplate, AnalysisJob, CodingAnnotation, CodingAdjudication,
    CodingBatch, CodingUnit, CodingUnitAnnotation, ExpertAnnotation, CodingUnitAdjudication,
    ExportJob, AuditLog, RunQualityReview,
    ModelTrainingJob, TextEmbeddingCache,
    ModelPredictionRun, ModelPredictionResult,
)

__all__ = [
    "Base",
    "User",
    "AssessmentTask", "QuestionPath",
    "ScaleDimensionGroup", "ScaleItem",
    "AssessmentSession", "DialogueTurn", "CodedSegment",
    "AudioChunk", "TranscriptSegment", "InteractionEvent",
    "MetacognitiveProfile", "MetacognitionMeasurement", "MeasurementCorrection", "LearningSuggestion", "ConsistencyReport",
    "AssessmentRun", "QuestionnaireResponse", "TaskOrderAssignment",
    "Notification",
    "SystemConfig", "SystemConfigHistory",
    "AsrJob", "TranscriptVersion",
    "ExtractionJob", "ExtractionCandidate", "ExtractionCandidateRevision",
    "NarrationAsset",
    "MethodTemplate", "AnalysisJob", "CodingAnnotation",
    "CodingAdjudication", "CodingBatch", "CodingUnit",
    "CodingUnitAnnotation", "ExpertAnnotation", "CodingUnitAdjudication",
    "ExportJob", "AuditLog", "RunQualityReview",
    "ModelTrainingJob", "TextEmbeddingCache",
    "ModelPredictionRun", "ModelPredictionResult",
]

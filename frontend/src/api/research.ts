import type { AxiosRequestConfig } from 'axios'
import apiClient from './client'

export interface MethodTemplate {
  id: string
  template_key: 'report_prompt' | 'metacognitive_extractor'
  version: string
  kind: 'prompt' | 'scoring' | 'intervention'
  content: string
  is_active: boolean
  created_at: string
}

export interface TemplateAudit {
  id: string
  action: 'template.create_activate' | 'template.activate' | 'template.rollback' | 'template.replace'
  template_key: MethodTemplate['template_key']
  from_version: string | null
  to_version: string | null
  actor_id: string | null
  actor_name: string | null
  created_at: string
}

export interface AnalysisJob {
  id: string
  run_id: string
  status: 'running' | 'completed' | 'failed'
  progress: number
  error_message: string
  result_profile_id: string | null
}

export interface CodingReviewer {
  id: string
  username: string
  name: string
  role: 'teacher' | 'admin'
}

export interface CodingScopeStudent {
  id: string
  username: string
  name: string
  class_group: string | null
}

export interface CodingBatchScope {
  run_ids?: string[]
  class_groups: string[]
  user_ids: string[]
  task_ids: string[]
  completed_from: string | null
  completed_to: string | null
  exclude_previously_batched: boolean
}

export interface CodingBatchScopeOptions {
  class_groups: string[]
  students: CodingScopeStudent[]
  tasks: Array<{
    id: string
    title: string
    protocol_order: number
  }>
  earliest_completed_at: string | null
  latest_completed_at: string | null
  transcript_segment_count: number
  coding_ready_segment_count: number
}

export interface CodingBatchPreview {
  student_count: number
  run_count: number
  session_count: number
  segment_count: number
  transcript_segment_count: number
  coding_ready_segment_count: number
  unreviewed_candidate_count: number
  previously_batched_segment_count: number
  selected_students: CodingScopeStudent[]
}

export interface CodingBatch {
  id: string
  name: string
  status: 'active' | 'completed' | 'archived'
  reviewer_a_id: string
  reviewer_a_name: string
  reviewer_b_id: string
  reviewer_b_name: string
  adjudicator_id: string
  adjudicator_name: string
  rubric_version: string
  scope_filter: CodingBatchScope | null
  scope_summary: {
    student_count: number
    run_count: number
    session_count: number
    segment_count: number
    human_reviewed_count?: number
    ai_only_unreviewed_count?: number
  } | null
  unit_count: number
  resolved_count: number
  disputed_count: number
  reviewer_a_completed: number
  reviewer_b_completed: number
  created_at: string
  completed_at: string | null
}

export interface CodingUnitAssignment {
  segment_id: string
  unit_id: string
  batch_id: string
  batch_name: string
  session_id: string
  run_id: string | null
  task_id: string
  audio_id: string | null
  participant_id: string | null
  sequence_no: number
  segment: string
  raw_text: string
  clean_text: string
  context_before: string
  context_after: string
  started_at_ms: number
  ended_at_ms: number
  reviewer_slot: 'A' | 'B'
  annotation_status: 'annotated' | 'unannotated'
  current_expert_label: ExpertLabel | null
  current_note: string
  annotation_created_at: string | null
  annotation_updated_at: string | null
  completed_units: number
  total_units: number
}

export interface CodingUnitDisagreement {
  segment_id: string
  unit_id: string
  batch_id: string
  batch_name: string
  session_id: string
  run_id: string | null
  task_id: string
  audio_id: string | null
  participant_id: string | null
  sequence_no: number
  segment: string
  raw_text: string
  clean_text: string
  context_before: string
  context_after: string
  started_at_ms: number
  ended_at_ms: number
  annotations: Array<{
    reviewer_slot: 'A' | 'B'
    expert_label: ExpertLabel
    note: string
  }>
}

export type ExpertLabel = 'monitoring' | 'regulation' | 'evaluation'

export interface ExpertDatasetStats {
  resolved_segment_count: number
  individual_annotation_count: number
  label_distribution: Record<ExpertLabel, number>
}

export interface ResearchDashboard {
  completed_runs: number
  reports: number
  review_pending: number
  publishable: number
  published: number
  quality: {
    eligible: number
    review_required: number
    ineligible: number
    excluded: number
  }
  unanalyzed_runs: Array<{
    run_id: string
    user_id: string
    user_name?: string
    username?: string
    class_group?: string
    tasks?: Array<{
      task_id: string
      title: string
      sequence_no: number
    }>
    completed_at?: string
  }>
  recent_reports: Array<{
    id: string
    run_id: string
    user_id: string
    user_name: string
    username: string
    score: number
    status: string
    requires_review_count: number
    /** null means no authoritative fixed blinded-coding batch exists yet. */
    double_review_pending: number | null
    quality_status: string
    generated_at: string
  }>
}

export interface MacroAnalytics {
  class_name: string
  selected_participant_id: string | null
  available_participants: Array<{
    id: string
    name: string
    username: string
    class_group: string | null
  }>
  generated_at: string
  available_class_groups: string[]
  sample_count: number
  reference_sample_count: number
  class_averages: Array<{ dimension: 'monitoring' | 'controlDebugging' | 'evaluation'; label: string; score: number; max: number }>
  reference_averages: Array<{ dimension: 'monitoring' | 'controlDebugging' | 'evaluation'; label: string; score: number; max: number }>
  profile_source: string
  radar_profiles: {
    selected: MacroRadarProfile
    participant: MacroRadarProfile | null
    class_group: MacroRadarProfile | null
    overall: MacroRadarProfile
  }
  order_balance: {
    groupAB: MacroOrderGroup
    groupBA: MacroOrderGroup
    test: {
      available: boolean
      metric: string
      t_statistic: number | null
      p_value: number | null
      levene_p_value: number | null
      interpretation: string
    }
  }
  dimension_distribution: {
    primary_source: 'expert_consensus' | 'production_model' | 'admin_upload' | 'hybrid' | 'none'
    counts: Record<'monitoring' | 'controlDebugging' | 'evaluation', number>
    total: number
    expert_consensus_total: number
    production_model_total: number
  }
  pipeline_status: {
    database: 'available'
    aggregation_latency_ms: number
    asr: { statuses: Record<string, number>; terminal_count: number; success_rate: number | null }
    extraction: { statuses: Record<string, number>; total: number }
    classification: { eligible_candidates: number; classified_candidates: number; coverage_rate: number | null }
  }
}

export interface MacroRadarProfile {
  scope: 'participant' | 'class' | 'overall' | 'accessible'
  label: string
  counts: Record<'monitoring' | 'controlDebugging' | 'evaluation', number>
  percentages: Record<'monitoring' | 'controlDebugging' | 'evaluation', number>
  total: number
  effective_dialogue_count: number
  denominator_breakdown: Record<string, number>
  fallback_dialogue_count: number
  unclassified_count: number
  score_available: boolean
  sample_count: number
  primary_source: 'expert_consensus' | 'production_model' | 'admin_upload' | 'hybrid' | 'none'
  scores: Array<{
    dimension: 'monitoring' | 'controlDebugging' | 'evaluation'
    label: string
    score: number
    max: number
  }>
}

export interface MacroOrderGroup {
  name: string
  count: number
  scoreCount: number
  avgDurationMin: number | null
  avgScore: number | null
  acceptedCandidateDensity: number | null
}

export interface QualityCheck {
  key: string
  label: string
  status: 'pass' | 'warning' | 'fail'
  message: string
}

export interface RunQuality {
  run_id: string
  user_id: string
  username: string
  name: string
  class_group: string | null
  completed_at: string | null
  protocol_version: string
  automatic_status: 'passed' | 'warning' | 'failed'
  effective_status: 'eligible' | 'review_required' | 'ineligible' | 'included' | 'included_override' | 'excluded'
  decision: 'automatic' | 'included' | 'excluded'
  decision_reason: string
  reviewed_by_name: string | null
  reviewed_at: string | null
  checks: QualityCheck[]
}

export interface ResearchAnalytics {
  quality: {
    included_run_count: number
    completed_run_count: number
  }
  agreement: {
    double_coded_segments: number
    dimension_percent_agreement: number | null
    cohen_kappa: number | null
    score_pearson_r: number | null
    score_mae: number | null
    human_ai_segments: number
    human_ai_percent_agreement: number | null
    human_ai_cohen_kappa: number | null
    human_ai_frequency_pearson_r: number | null
    human_ai_frequency_mae: number | null
    human_ai_by_dimension: Record<string, {
      support: number
      precision: number | null
      recall: number | null
      f1: number | null
    }>
  }
  questionnaire: {
    complete_sample_size: number
    item_count: number
    cronbach_alpha: number | null
    notice: string
  }
}

export interface TaskOrderStudent {
  user_id: string
  username: string
  name: string
  class_group: string | null
  ordered_task_ids: string[]
  order_code: 'AB' | 'BA' | 'CUSTOM'
  assigned_by: string | null
  assigned_at: string | null
  has_in_progress_run: boolean
}

export interface TaskOrderOverview {
  tasks: Array<{
    id: string
    title: string
    protocol_order: number
  }>
  students: TaskOrderStudent[]
  total: number
  page: number
  page_size: number
}

export interface ResearchExportJob {
  id: string
  status: 'queued' | 'preparing' | 'running' | 'completed' | 'failed' | 'expired'
  export_type: 'research_csv' | 'audio_transcript_zip'
  row_count: number
  progress: number
  download_url: string | null
  error_message: string
}

export interface ResearchExportDownloadTicket {
  url: string
  expires: number
  filename: string
}

export interface AudioTranscriptExportPreview {
  completed_session_count: number
  candidate_session_count: number
  sessions_without_candidates: number
  candidate_total: number
  accepted_count: number
  rejected_count: number
  pending_count: number
  review_complete: boolean
  previous_export_at: string | null
  previous_review_complete: boolean | null
  newly_reviewed_count: number
  newly_accepted_count: number
  incremental_session_count: number
}

export interface ModelTrainingJob {
  id: string
  version: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  stage: string
  progress: number
  current_fold: number | null
  total_folds: number
  heartbeat_at: string | null
  estimated_remaining_seconds: number | null
  sample_count: number
  label_distribution: Record<string, number> | null
  dataset_fingerprint: string | null
  config_snapshot: Record<string, unknown> | null
  metrics: {
    accuracy?: number
    macro_precision?: number
    macro_recall?: number
    weighted_precision?: number
    weighted_recall?: number
    macro_specificity?: number
    macro_f1?: number
    weighted_f1?: number
    cross_entropy?: number
    macro_auc_ovr?: number
    folds?: Array<{
      fold: number
      train_sample_count?: number
      sample_count: number
      train_label_distribution?: Record<string, number>
      test_label_distribution?: Record<string, number>
      train_accuracy?: number
      train_macro_f1?: number
      accuracy: number
      macro_precision: number
      macro_recall: number
      weighted_precision?: number
      weighted_recall?: number
      macro_auc_ovr?: number | null
      cross_entropy?: number | null
      per_class_auc?: Record<string, number | null>
      train_participant_count?: number | null
      test_participant_count?: number | null
      participant_overlap_count?: number | null
      subject_disjoint_verified?: boolean | null
      macro_specificity?: number
      macro_f1: number
    }>
    confusion_matrix?: number[][]
    per_class?: Record<string, {
      precision: number
      recall: number
      specificity?: number
      f1: number
      support: number
    }>
    roc_curves?: Record<string, {
      fpr: number[]
      tpr: number[]
      auc: number
    }>
    roc_evaluation?: {
      source: string
      aggregation: string
      strategy: string
      score_type: string
      sample_count: number
      every_sample_evaluated_once: boolean
      external_holdout: boolean
    }
    evaluation_summary?: {
      method: string
      split_strategy: string
      sample_count: number
      participant_count?: number | null
      label_distribution: Record<string, number>
      fold_count: number
      out_of_fold_sample_count: number
      every_sample_evaluated_once: boolean
      final_model_refit_on_all_data: boolean
      external_holdout: boolean
    }
    split_strategy?: 'subject_grouped_stratified_5fold' | 'sentence_stratified_5fold'
    subject_leakage_risk?: boolean
    evaluation_warning?: string
    classifier_parameters?: Record<string, string | number | boolean>
    hyperparameters_tuned?: boolean
    hyperparameter_source?: 'default' | 'manual'
  } | null
  is_active: boolean
  artifact_sha256: string | null
  cancel_requested: boolean
  parent_job_id: string | null
  error_message: string
  created_at: string
  started_at: string | null
  completed_at: string | null
  activated_at: string | null
  updated_at: string | null
}

export interface ModelTrainingAudit {
  id: string
  action: string
  job_id: string | null
  version: string | null
  actor_name: string | null
  detail: Record<string, unknown> | null
  created_at: string
}

export type ModelExperimentType =
  | 'tfidf_linear_svc'
  | 'embedding_linear_svc'
  | 'embedding_logistic'
  | 'embedding_random_forest'
  | 'embedding_xgboost'
  | 'embedding_lightgbm'
  | 'embedding_catboost'

export type ModelHyperparameterValue = string | number | boolean

export interface ModelHyperparameterDefinition {
  type: 'number' | 'integer' | 'choice'
  label: string
  default: ModelHyperparameterValue
  min?: number
  max?: number
  step?: number
  choices?: string[]
  description: string
}

export type ModelHyperparameterCatalog = Record<ModelExperimentType, {
  parameters: Record<string, ModelHyperparameterDefinition>
  defaults: Record<string, ModelHyperparameterValue>
}>

export type ModelDatasetSource = 'system_gold' | 'uploaded'

export interface ModelTrainingDataset {
  id: string
  name: string
  source: ModelDatasetSource
  original_filename: string | null
  sample_count: number
  training_sample_count: number
  excluded_non_metacognitive_count: number
  participant_count: number
  has_participant_ids: boolean
  split_strategy: string
  label_distribution: Record<string, number>
  training_label_distribution: Record<string, number>
  training_labels: number[]
  fingerprint: string
  created_by: string | null
  created_at: string
}

export interface ModelEvaluation {
  model_id: string
  model_version: string
  dataset_id: string | null
  dataset_version: string | null
  dataset_fingerprint: string | null
  comparison_group_id: string | null
  comparison_group_label: string | null
  trained_at: string | null
  labels: Array<{ id: number; name: string }>
  summary: {
    accuracy: number | null
    macro_precision: number | null
    macro_recall: number | null
    weighted_precision: number | null
    weighted_recall: number | null
    macro_specificity: number | null
    macro_f1: number | null
    weighted_f1: number | null
    macro_auc_ovr: number | null
    cross_entropy: number | null
  }
  per_class: Array<{
    label_id: number
    label_name: string
    precision: number | null
    recall: number | null
    specificity?: number | null
    f1: number | null
    support: number | null
  }>
  confusion_matrix: number[][]
  confusion_pairs: Array<{
    actual_label: string
    predicted_label: string
    count: number
  }>
  cross_validation: {
    fold_count: number
    macro_f1_mean: number | null
    macro_f1_std: number | null
    macro_f1_min: number | null
    macro_f1_max: number | null
    macro_f1_range: number | null
    macro_auc_mean: number | null
    macro_auc_std: number | null
    macro_auc_min: number | null
    macro_auc_max: number | null
    macro_auc_range: number | null
    macro_f1_interval: MetricFoldInterval
    macro_auc_interval: MetricFoldInterval
    per_class_auc_intervals: Record<string, MetricFoldInterval>
    train_macro_f1_mean: number | null
    train_test_macro_f1_gap: number | null
    train_sample_counts: number[]
    test_sample_counts: number[]
    folds: NonNullable<NonNullable<ModelTrainingJob['metrics']>['folds']>
    subject_disjoint_audit: {
      available: boolean
      all_folds_verified: boolean
      maximum_overlap_count: number | null
      note: string
    }
  }
  dataset: {
    version: string | null
    fingerprint: string | null
    sample_count: number
    participant_count: number | null
    class_count: number
    class_distribution: Record<string, number> | null
    split_strategy: string | null
    random_seed: number | null
    external_holdout: boolean
  }
  model_info: {
    feature_type: string | null
    classifier: string | null
    embedding_provider: string | null
    embedding_model: string | null
    training_pipeline_version: number | null
    classifier_parameters: Record<string, ModelHyperparameterValue>
    hyperparameters_tuned: boolean
    hyperparameter_source: 'default' | 'manual'
    is_active: boolean
  }
  roc_curves: NonNullable<ModelTrainingJob['metrics']>['roc_curves'] | null
  roc_evaluation: NonNullable<ModelTrainingJob['metrics']>['roc_evaluation'] | null
  subject_leakage_risk: boolean | null
  evaluation_warning: string | null
  error_analysis: {
    total_error_count: number
    displayed_error_count: number
    cases: Array<{
      participant_id: string | null
      text: string
      true_label: number
      predicted_label: number
    }>
    metadata_availability: Record<string, boolean>
    note: string
  } | null
  evidence_coverage: {
    subject_level_split: boolean
    fold_uncertainty: boolean
    independent_external_holdout: boolean
    pairwise_statistical_test: boolean
    cross_task_transfer: boolean
    expert_reliability_bound_to_dataset: boolean
    asr_quality_bound_to_dataset: boolean
    notes: Record<string, string>
  }
  source: {
    type: 'training_evaluation_result'
    manifest_schema_version: number
    legacy_synthesized: boolean
    metrics_sha256: string
  }
}

export interface MetricFoldInterval {
  mean: number | null
  std: number | null
  ci95_low: number | null
  ci95_high: number | null
  n: number
  method?: string
}

export interface ModelEvaluationVersion {
  version_id: string
  display_version: string
  dataset_version: string | null
  dataset_fingerprint: string | null
  trained_at: string
  comparable: boolean
  comparison_warning: string | null
  best_model_id: string | null
  models: ModelEvaluation[]
}

export interface ModelEvaluationIndex {
  schema_version: number
  primary_metric: 'macro_f1'
  tie_breakers: string[]
  latest_version_id: string | null
  versions: ModelEvaluationVersion[]
  errors: Array<{ version_id: string; error: string }>
}

export interface AiEvaluationModel {
  id: string
  version: string
  experiment_type: string
  display_name: string
  macro_f1: number | null
  weighted_f1: number | null
  is_active: boolean
  is_best: boolean
  completed_at: string | null
}

export interface AiEvaluationScopeItem {
  session_id: string
  participant_id: string
  participant_name: string
  username: string
  class_group: string | null
  task_id: string
  task_title: string
  completed_at: string | null
  candidate_count: number
  reviewed_count: number
  pending_count: number
  rejected_count: number
  classified_count: number
  training_participant: boolean
  dimension_counts: Record<string, number>
}

export interface AiEvaluationOverview {
  enabled: boolean
  can_activate: boolean
  active_model: AiEvaluationModel | null
  best_model_id: string | null
  models: AiEvaluationModel[]
  training_source: 'system_gold' | 'uploaded' | 'none'
  training_source_label: string
  scope_items: AiEvaluationScopeItem[]
}

export interface AiEvaluationRunResult {
  model_id: string
  model_version: string
  processed: number
  remaining: number
  skipped_rejected: number
  source_counts: Record<string, number>
  dimension_counts: Record<string, number>
}

export const researchApi = {
  getAiEvaluationOverview() {
    return apiClient.get<AiEvaluationOverview>('/research/ai-evaluation/overview')
  },
  runAiEvaluation(scope: 'all' | 'student' | 'session' | 'task', ids: string[], batchSize = 100) {
    return apiClient.post<AiEvaluationRunResult>('/research/ai-evaluation/classify', {
      scope, ids, batch_size: batchSize
    }, { timeout: 120_000 })
  },
  createModelTrainingJob(
    version: string,
    experimentType: ModelExperimentType,
    datasetSource: ModelDatasetSource,
    datasetId: string | null,
    hyperparameters: Record<string, ModelHyperparameterValue> = {}
  ) {
    return apiClient.post<ModelTrainingJob>('/research/model-training/jobs', {
      version,
      experiment_type: experimentType,
      dataset_source: datasetSource,
      dataset_id: datasetId,
      hyperparameters
    })
  },
  createModelTrainingSuite(
    versionPrefix: string,
    datasetSource: ModelDatasetSource,
    datasetId: string | null,
    hyperparameters: Partial<Record<ModelExperimentType, Record<string, ModelHyperparameterValue>>> = {},
    experimentTypes: ModelExperimentType[] | null = null
  ) {
    return apiClient.post<ModelTrainingJob[]>('/research/model-training/jobs/suite', {
      version_prefix: versionPrefix,
      dataset_source: datasetSource,
      dataset_id: datasetId,
      hyperparameters,
      experiment_types: experimentTypes
    })
  },
  getModelHyperparameters() {
    return apiClient.get<ModelHyperparameterCatalog>('/research/model-training/hyperparameters')
  },
  listModelTrainingDatasets() {
    return apiClient.get<ModelTrainingDataset[]>('/research/model-training/datasets')
  },
  downloadModelTrainingDatasetTemplate() {
    return apiClient.get<Blob>('/research/model-training/datasets/template', {
      responseType: 'blob',
      timeout: 60_000
    })
  },
  uploadModelTrainingDataset(name: string, file: File) {
    const form = new FormData()
    form.append('name', name)
    form.append('file', file)
    return apiClient.post<ModelTrainingDataset>('/research/model-training/datasets/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120_000
    })
  },
  listModelTrainingJobs() {
    return apiClient.get<ModelTrainingJob[]>('/research/model-training/jobs')
  },
  listModelEvaluations() {
    return apiClient.get<ModelEvaluationIndex>('/research/model-training/evaluations')
  },
  deleteModelTrainingJob(jobId: string) {
    return apiClient.delete<{
      status: 'deleted'
      job_id: string
      version: string
      artifact_removed: boolean
    }>(`/research/model-training/jobs/${jobId}`)
  },
  deleteModelTrainingJobs(jobIds: string[]) {
    return apiClient.post<{
      status: 'deleted'
      deleted_count: number
      items: Array<{ status: 'deleted'; job_id: string; version: string; artifact_removed: boolean }>
    }>('/research/model-training/jobs/batch-delete', { job_ids: jobIds })
  },
  activateModelTrainingJob(jobId: string) {
    return apiClient.post<ModelTrainingJob>(`/research/model-training/jobs/${jobId}/activate`)
  },
  deactivateModelTrainingJob(jobId: string) {
    return apiClient.post<ModelTrainingJob>(`/research/model-training/jobs/${jobId}/deactivate`)
  },
  cancelModelTrainingJob(jobId: string) {
    return apiClient.post<ModelTrainingJob>(`/research/model-training/jobs/${jobId}/cancel`)
  },
  retryModelTrainingJob(jobId: string) {
    return apiClient.post<ModelTrainingJob>(`/research/model-training/jobs/${jobId}/retry`)
  },
  listModelTrainingAudit() {
    return apiClient.get<ModelTrainingAudit[]>('/research/model-training/audit')
  },
  exportModelTrainingReport(jobId: string) {
    return apiClient.get<Blob>(`/research/model-training/jobs/${jobId}/export`, {
      responseType: 'blob',
      timeout: 120_000
    })
  },
  exportModelErrorCases(jobId: string) {
    return apiClient.get<Blob>(`/research/model-training/jobs/${jobId}/error-cases/export`, {
      responseType: 'blob',
      timeout: 120_000
    })
  },
  exportModelTrainingComparison(jobIds?: string[]) {
    return apiClient.get<Blob>('/research/model-training/comparison/export', {
      params: jobIds?.length ? { job_ids: jobIds.join(',') } : undefined,
      responseType: 'blob',
      timeout: 120_000
    })
  },
  listTemplates() {
    return apiClient.get<MethodTemplate[]>('/research/templates')
  },
  replaceTemplate(templateKey: string, data: { version: string; kind: string; content: string }) {
    return apiClient.put<MethodTemplate>(`/research/templates/${templateKey}`, data)
  },
  activateTemplate(templateKey: string, templateId: string) {
    return apiClient.post<MethodTemplate>(`/research/templates/${templateKey}/${templateId}/activate`)
  },
  listTemplateAudit(limit = 200) {
    return apiClient.get<TemplateAudit[]>('/research/templates/audit', { params: { limit } })
  },
  startAnalysis(runId: string, reanalyze = false) {
    return apiClient.post<AnalysisJob>(`/research/analysis/runs/${runId}`, { reanalyze })
  },
  dashboard() {
    return apiClient.get<ResearchDashboard>('/research/dashboard')
  },
  listRunQuality(params: {
    page?: number
    page_size?: number
    search?: string
    status_filter?: string
  } = {}) {
    return apiClient.get<RunQuality[]>('/research/quality/runs', { params })
  },
  decideRunQuality(runId: string, decision: 'automatic' | 'included' | 'excluded', reason = '') {
    return apiClient.put<RunQuality>(`/research/quality/runs/${runId}/decision`, {
      decision,
      reason
    })
  },
  analytics(config?: AxiosRequestConfig) {
    return apiClient.get<ResearchAnalytics>('/research/analytics', config)
  },
  listCodingReviewers() {
    return apiClient.get<CodingReviewer[]>('/research/review/reviewers')
  },
  listCodingBatches() {
    return apiClient.get<CodingBatch[]>('/research/review/batches')
  },
  codingBatchScopeOptions() {
    return apiClient.get<CodingBatchScopeOptions>(
      '/research/review/batches/scope-options'
    )
  },
  previewCodingBatch(data: CodingBatchScope) {
    return apiClient.post<CodingBatchPreview>(
      '/research/review/batches/preview',
      data
    )
  },
  createCodingBatch(data: {
    name: string
    reviewer_a_id: string
    reviewer_b_id: string
    adjudicator_id: string
    allow_unreviewed_candidates?: boolean
  } & CodingBatchScope) {
    return apiClient.post<CodingBatch>('/research/review/batches', data)
  },
  updateCodingBatchAssignments(batchId: string, data: {
    reviewer_a_id: string
    reviewer_b_id: string
    adjudicator_id: string
  }) {
    return apiClient.put<CodingBatch>(
      `/research/review/batches/${batchId}/assignments`,
      data
    )
  },
  listCodingUnitAssignments(annotationStatus: 'unannotated' | 'annotated' | 'all' = 'unannotated') {
    return apiClient.get<CodingUnitAssignment[]>('/research/review/unit-assignments', {
      params: { annotation_status: annotationStatus }
    })
  },
  saveExpertAnnotation(unitId: string, expertLabel: ExpertLabel, note: string) {
    return apiClient.put(`/research/review/units/${unitId}/expert-annotation`, {
      expert_label: expertLabel,
      note
    })
  },
  listCodingUnitDisagreements() {
    return apiClient.get<CodingUnitDisagreement[]>(
      '/research/review/unit-disagreements'
    )
  },
  adjudicateCodingUnit(unitId: string, dimension: ExpertLabel, note: string) {
    return apiClient.post(`/research/review/units/${unitId}/adjudicate`, {
      dimension,
      note
    })
  },
  expertDatasetStats() {
    return apiClient.get<ExpertDatasetStats>('/research/review/training-dataset/stats')
  },
  exportExpertDataset(
    textSource: 'clean_text' | 'raw_text' = 'clean_text',
    labelMode: 'resolved' | 'individual' = 'resolved'
  ) {
    return apiClient.get<Blob>('/research/review/training-dataset/export', {
      params: { text_source: textSource, label_mode: labelMode },
      responseType: 'blob'
    })
  },
  publishReport(reportId: string, note = '') {
    return apiClient.post(`/research/reports/${reportId}/publish`, { note })
  },
  bulkPublishReports(reportIds: string[], note = '') {
    return apiClient.post<{ processed: number; skipped: number; errors: string[] }>(
      '/research/reports/bulk-publish',
      { report_ids: reportIds, note }
    )
  },
  createExport() {
    return apiClient.post<ResearchExportJob>('/research/exports')
  },
  previewAudioTranscriptExport(includeAudio = true) {
    return apiClient.get<AudioTranscriptExportPreview>('/research/exports/audio-transcripts/preview', {
      params: { include_audio: includeAudio }
    })
  },
  createAudioTranscriptExport(mode: 'all' | 'incremental' | 'accepted_only' = 'all', acknowledgeIncompleteReview = false, includeAudio = true) {
    return apiClient.post<ResearchExportJob>('/research/exports/audio-transcripts', {
      mode,
      include_audio: includeAudio,
      acknowledge_incomplete_review: acknowledgeIncompleteReview
    })
  },
  getExportStatus(jobId: string) {
    return apiClient.get<ResearchExportJob>(`/research/exports/${jobId}`)
  },
  downloadExport(jobId: string) {
    return apiClient.post<ResearchExportDownloadTicket>(
      `/research/exports/${jobId}/download-ticket`
    )
  },
  taskOrderAssignments(params: { page?: number; page_size?: number; search?: string } = {}) {
    return apiClient.get<TaskOrderOverview>('/assessment/task-order/assignments', { params })
  },
  setTaskOrder(userId: string, orderedTaskIds: string[]) {
    return apiClient.put<TaskOrderStudent>(
      `/assessment/task-order/assignments/${userId}`,
      { ordered_task_ids: orderedTaskIds }
    )
  },
  balanceTaskOrders(userIds: string[]) {
    return apiClient.post<TaskOrderOverview>(
      '/assessment/task-order/assignments/balance',
      { user_ids: userIds }
    )
  },
  getMacroAnalytics(classGroup = 'all', participantId?: string) {
    return apiClient.get<MacroAnalytics>('/research/macro-analytics', {
      params: { class_group: classGroup, participant_id: participantId || undefined }
    })
  }
}

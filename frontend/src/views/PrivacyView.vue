<script setup lang="ts">
import AppPageHeader from '../components/ui/AppPageHeader.vue'
</script>

<template>
  <div class="privacy-page">
    <AppPageHeader
      eyebrow="研究参与者权益"
      title="隐私与数据说明"
      icon="bi-shield-check"
      description="了解系统采集哪些数据、由谁访问、保存多久，以及如何申请退出研究。"
    >
      <template #meta>
        <div class="privacy-version">
          <span><i class="bi bi-file-earmark-check" />版本 2026.08</span>
          <span>更新日期：2026 年 8 月 14 日</span>
        </div>
      </template>
    </AppPageHeader>

    <div class="privacy-summary" role="note">
      <i class="bi bi-info-circle-fill" />
      <p>
        系统在采集阶段会通过登录账号关联测评数据，以便保存进度、校订转录和处理退出申请；
        对外研究分析与成果呈现应使用去标识化数据，不公开姓名、账号或联系方式。
      </p>
    </div>

    <div class="privacy-grid">
      <section class="privacy-card">
        <span class="privacy-icon"><i class="bi bi-database" /></span>
        <div><h3>采集的数据</h3><p>系统保存麦克风录音分片、浏览器实时字幕、权威转录、作答时长、交互事件、任务后问卷、AI 候选与人工复核记录。问卷中主动填写的姓名或微信名同样属于可识别研究数据。</p></div>
      </section>
      <section class="privacy-card">
        <span class="privacy-icon"><i class="bi bi-bullseye" /></span>
        <div><h3>使用目的</h3><p>数据仅用于元认知测评、学习反馈、研究质量控制和经授权的统计分析，不用于广告推荐、商业画像或本研究以外的自动决策。</p></div>
      </section>
      <section class="privacy-card">
        <span class="privacy-icon"><i class="bi bi-person-lock" /></span>
        <div><h3>访问与导出</h3><p>学生只能访问自己的数据；教师仅能访问其职责范围内的班级；管理员按研究管理职责访问。获授权的教师和管理员可导出包含姓名、账号、班级、数据库 ID、问卷、转录与候选的数据，并可在需要时选择包含录音；创建、下载凭证和下载行为均写入审计日志。</p></div>
      </section>
      <section class="privacy-card">
        <span class="privacy-icon"><i class="bi bi-calendar-check" /></span>
        <div><h3>保存期限与销毁</h3><p>可识别研究数据原则上保存至项目结题及成果核验完成后 5 年；如学校、伦理审查或资助管理另有更严格要求，从其规定。期限届满后删除可识别源数据，或仅保留无法再关联个人的统计结果。</p></div>
      </section>
      <section class="privacy-card">
        <span class="privacy-icon"><i class="bi bi-box-arrow-left" /></span>
        <div><h3>退出与删除申请</h3><p>在数据进入不可逆的汇总分析或公开成果前，参与者可联系组织本次测评的教师或项目管理员提出退出，并提供账号与大致测评时间用于定位。核验后将按研究管理要求删除可识别的录音、转录、问卷、候选与编码记录。</p></div>
      </section>
      <section class="privacy-card">
        <span class="privacy-icon"><i class="bi bi-person-badge" /></span>
        <div><h3>责任主体与联系渠道</h3><p>数据责任主体为本项目课题负责人及其授权研究管理员。如需咨询、更正或退出，请优先联系组织本次测评的教师；无法联系时，可由学校或项目组织方转交课题负责人处理。</p></div>
      </section>
    </div>

    <div class="privacy-boundary">
      <i class="bi bi-exclamation-circle" />
      <div><strong>研究边界</strong><p>系统报告是阶段性学习反馈，不是临床诊断，也不能替代正式心理测量和专业判断。站内消息只保存事件摘要和链接，不包含完整录音、字幕原文、密码或模型密钥。</p></div>
    </div>
  </div>
</template>

<style scoped>
.privacy-page{max-width:1040px;margin:0 auto}.privacy-version{display:flex;flex-wrap:wrap;gap:.5rem 1rem;margin-top:.7rem;color:var(--color-text-muted);font-size:.78rem}.privacy-version span{display:inline-flex;align-items:center;gap:.35rem}.privacy-summary,.privacy-boundary{display:flex;align-items:flex-start;gap:.8rem;border-radius:var(--radius-lg)}.privacy-summary{margin-bottom:1rem;padding:1rem 1.1rem;border:1px solid var(--color-border);background:var(--color-primary-soft);color:var(--color-primary)}.privacy-summary>i{margin-top:.1rem;font-size:1.1rem}.privacy-summary p,.privacy-boundary p{margin:0;line-height:1.75}.privacy-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.privacy-card{display:flex;align-items:flex-start;gap:1rem;padding:1.25rem;border:1px solid var(--color-border);border-radius:var(--radius-lg);background:var(--color-surface);box-shadow:var(--shadow-xs)}.privacy-icon{width:42px;height:42px;display:grid;flex:0 0 auto;place-items:center;border-radius:12px;background:var(--color-primary-soft);color:var(--primary);font-size:1.15rem}.privacy-card h3{margin:0 0 .45rem;font-size:1rem}.privacy-card p{margin:0;color:var(--color-text-secondary);font-size:.85rem;line-height:1.75}.privacy-boundary{margin-top:1rem;padding:1rem 1.1rem;border:1px solid var(--color-border);background:var(--color-warning-soft);color:var(--color-warning)}.privacy-boundary>i{margin-top:.1rem;font-size:1.1rem}.privacy-boundary strong{display:block;margin-bottom:.2rem}.privacy-boundary p{font-size:.84rem}@media(max-width:700px){.privacy-grid{grid-template-columns:1fr}.privacy-card{padding:1rem}.privacy-summary,.privacy-boundary{padding:.9rem}.privacy-version{display:grid;gap:.25rem}}
</style>

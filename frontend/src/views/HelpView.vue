<template>
  <div class="info-page">
    <h3>帮助与使用指南</h3>
    <p class="text-muted">开始测评前请完成以下检查。</p>
    <div class="row g-3">
      <div class="col-md-6"><div class="help-card"><i class="bi bi-browser-chrome" /><div><h5>推荐浏览器</h5><p>使用最新版 Chrome 或 Edge。其他浏览器可能不支持实时字幕。</p></div></div></div>
      <div class="col-md-6"><div class="help-card"><i class="bi bi-mic" /><div><h5>麦克风权限</h5><p>在浏览器地址栏允许麦克风，选择安静环境并检查系统输入设备。</p></div></div></div>
      <div class="col-md-6"><div class="help-card"><i class="bi bi-chat-quote" /><div><h5>出声思维</h5><p>持续说出当前正在看、计算、判断和调整的内容，不必组织成完整解释。</p></div></div></div>
      <div class="col-md-6"><div class="help-card"><i class="bi bi-cloud-check" /><div><h5>保存与恢复</h5><p>正式任务会分片上传；页面刷新后可恢复未完成测评，但测评时仍应避免主动关闭页面。</p></div></div></div>
      <div class="col-12"><div class="help-card help-card-wide"><i class="bi bi-phone" /><div><h5>手机测评注意事项</h5><p>开始后请保持屏幕常亮并停留在测评页面，不要锁屏、切换应用或接听电话。系统或浏览器可能在这些情况下暂停麦克风；如发生中断，请回到页面并按提示确认录音状态与待上传数据。</p></div></div></div>
    </div>
    <div class="alert alert-info mt-4">实时字幕不可用时，系统仍可录制和上传音频，但当前版本的行为证据可能减少。</div>
  </div>
</template>
<style scoped>.info-page{max-width:950px;margin:0 auto}.help-card{height:100%;display:flex;gap:1rem;padding:1.25rem;border:1px solid var(--color-border);border-radius:var(--radius-lg);background:var(--color-surface);box-shadow:var(--shadow-sm)}.help-card>i{font-size:1.5rem;color:var(--color-primary)}.help-card h5{font-size:1rem}.help-card p{color:var(--color-text-secondary);font-size:.84rem;line-height:1.65;margin:0}</style>

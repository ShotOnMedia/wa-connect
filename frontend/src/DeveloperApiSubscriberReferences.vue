<template>
<section class="subscriber-reference-card">
  <div class="reference-head">
    <div>
      <p class="eyebrow">Universal subscriber resolver</p>
      <h2>Identifying a subscriber</h2>
      <p>Subscriber-targeting Developer API actions use the same resolver for messaging, custom fields, tags, conversation updates, flow reset and flow triggering.</p>
    </div>
    <span class="badge">WhatsApp + Telegram</span>
  </div>

  <div class="reference-grid">
    <article>
      <b>Buccaneer internal ID</b>
      <code>telegram:1</code>
      <small>Canonical channel + Buccaneer contact ID. This is the safest internal reference.</small>
    </article>
    <article>
      <b>Telegram user ID</b>
      <code>telegram_user:137205674</code>
      <small>Explicitly identifies the native user ID assigned by Telegram.</small>
    </article>
    <article>
      <b>Business Subscriber ID</b>
      <code>subscriber_id:27829640758</code>
      <small>Resolves the subscriber_id custom field, useful when an external system already knows this identifier.</small>
    </article>
    <article>
      <b>Bare identifier + channel</b>
      <code>"channel":"telegram", "subscriber":"27829640758"</code>
      <small>Convenient for integrations. Telegram resolution tries internal contact ID, Telegram user ID, then subscriber_id.</small>
    </article>
  </div>

  <div class="recommendation">
    <strong>Recommended for external integrations</strong>
    <p>Use an explicit reference such as <code>subscriber_id:27829640758</code> whenever the external system owns the business identifier. Explicit prefixes avoid ambiguity between Buccaneer IDs, platform IDs and business IDs.</p>
  </div>

  <div class="example">
    <div><b>Example — send a Telegram message using a business Subscriber ID</b><span>POST /api/v1/messages/send</span></div>
    <pre>{
  "channel": "telegram",
  "subscriber": "subscriber_id:27829640758",
  "message": "Hello from Buccaneer"
}</pre>
  </div>

  <p class="scope-note"><b>Where this applies:</b> body-first subscriber actions including Send Message, Set Fields, Tags, Conversation updates and Reset Flow, plus Trigger Flow subscriber resolution. Path-based endpoints that explicitly document <code>{id}</code> continue to use their documented path identifier format.</p>
</section>
</template>

<style scoped>
.subscriber-reference-card{background:#fff;border:1px solid #dbe6e1;border-radius:14px;padding:22px;margin-bottom:20px;color:#173126;box-shadow:0 8px 24px rgba(20,55,40,.035)}
.reference-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:18px}.reference-head h2{margin:3px 0 6px;font-size:20px}.reference-head p:last-child{margin:0;color:#71837a;max-width:820px;line-height:1.5}.eyebrow{margin:0;text-transform:uppercase;color:#119052;font-size:10px;font-weight:900;letter-spacing:.1em}.badge{white-space:nowrap;background:#e8f7ef;color:#087943;border-radius:999px;padding:6px 10px;font-size:10px;font-weight:900}.reference-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.reference-grid article{display:flex;flex-direction:column;gap:7px;border:1px solid #e1e9e5;background:#f8fbf9;border-radius:10px;padding:14px}.reference-grid b{font-size:12px}.reference-grid code,.recommendation code,.scope-note code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#edf3f0;color:#18573a;border-radius:5px;padding:3px 6px;width:max-content;max-width:100%;overflow-wrap:anywhere}.reference-grid small{color:#73847c;line-height:1.45}.recommendation{margin-top:12px;border-left:3px solid #18a45e;background:#eff9f3;padding:12px 14px;border-radius:0 9px 9px 0}.recommendation strong{font-size:12px}.recommendation p{margin:5px 0 0;color:#587066;font-size:12px;line-height:1.5}.example{margin-top:12px;border:1px solid #dfe7e3;border-radius:10px;overflow:hidden}.example>div{display:flex;justify-content:space-between;gap:12px;padding:10px 13px;background:#f7faf8;font-size:11px}.example>div span{color:#6f8178}.example pre{margin:0;padding:14px;background:#13251d;color:#d9f4e5;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}.scope-note{margin:12px 0 0;color:#6c7e75;font-size:11px;line-height:1.55}@media(max-width:850px){.reference-grid{grid-template-columns:1fr}.reference-head{flex-direction:column}.example>div{flex-direction:column}}
</style>

# Base Family Office HTML Reply Template (Natural Prose)

```html
<div style="font-family:'Avenir Next','Segoe UI',Arial,sans-serif;max-width:760px;margin:0 auto;padding:18px 20px;color:#182026;line-height:1.55;background:#ffffff;">
  <p style="margin:0 0 14px 0;font-size:14px;color:#1f2933;">{{salutation}}</p>

  <div style="font-size:14px;color:#1f2933;">
    {{reply_body_html}}
  </div>

  <div style="margin-top:16px;font-size:14px;color:#1f2933;">
    <p style="margin:0 0 4px 0;">{{closing}}</p>
    <p style="margin:0 0 2px 0;">{{signature_line}}</p>
    <p style="margin:0;font-size:12px;color:#5f6c7b;">{{footer_line}}</p>
  </div>
</div>
```

Usage notes:
- Use a real email shell: salutation, body, closing, signature.
- Keep the layout close to a normal human email, not a branded card or mini-report.
- Render the body as actual HTML email content, not plaintext-like lines inside an HTML wrapper.
- Add headings only when they improve readability.
- Use a compact table or chart only when it is materially clearer than prose.
- Default to inline parenthetical or embedded attribution when sources matter, using clean clickable HTML links when helpful.
- Add a short final source note only when the reply is research-heavy or cites enough sources that inline attribution would become awkward.

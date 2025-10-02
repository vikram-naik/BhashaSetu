# ingestion/webcrawl/views.py
# Presentation layer: Jinja templates & render helpers

from flask import render_template_string, url_for

LINKS_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Sentence Review — Links</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 8px; }
    th { background: #f2f2f2; text-align: left; }
    .pager { margin-top: 12px; }
    .count { color: #666; font-size: 0.9em; }
    a.button { padding: 6px 10px; background:#007bff; color:#fff; text-decoration:none; border-radius:4px; }
  </style>
</head>
<body>
  <h1>Sentence Review — Links</h1>
  <p class="count">Showing links {{ start }}–{{ end }} of {{ total_links }} (page {{ page }} of {{ total_pages }})</p>
  <table>
    <tr><th>Link</th><th>Sentences</th><th>Actions</th></tr>
    {% for link in links %}
    <tr>
      <td><a href="{{ url_for('view_link', link_id=link.id) }}" target="_blank">{{ link.url }}</a></td>
      <td>{{ link.count }}</td>
      <td>
        <a class="button" href="{{ url_for('view_link', link_id=link.id) }}">Review Sentences</a>
      </td>
    </tr>
    {% endfor %}
  </table>

  <div class="pager">
    {% if page > 1 %}
      <a href="{{ url_for('index') }}?page={{ page-1 }}" class="button">Prev</a>
    {% endif %}
    {% if page < total_pages %}
      <a href="{{ url_for('index') }}?page={{ page+1 }}" class="button">Next</a>
    {% endif %}
  </div>
</body>
</html>
"""

LINK_SENTENCES_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Sentences for {{ link_url }}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 8px; vertical-align: top; }
    th { background: #f2f2f2; text-align: left; }
    textarea { width: 100%; height: 60px; }
    .actions { display:flex; gap:8px; }
    .button { padding:6px 10px; background:#007bff; color:#fff; text-decoration:none; border-radius:4px; cursor:pointer; border:none; }
    .danger { background:#c0392b; }
    .muted { color:#666; font-size:0.9em; }
    .pager { margin-top: 12px; }
  </style>
</head>
<body>
  <a href="{{ url_for('index') }}">&larr; Back to links</a>
  <h1>Sentences for</h1>
  <p><a href="{{ link_url }}" target="_blank">{{ link_url }}</a></p>
  <p class="muted">Showing sentences {{ start }}–{{ end }} of {{ total }} (page {{ page }} of {{ total_pages }})</p>

  <form id="sentences-form">
    <table>
      <tr><th>Keep</th><th>Sentence</th><th>Actions</th></tr>
      {% for s in sentences %}
      <tr data-sid="{{ s.id }}">
        <td style="width:70px; text-align:center;">
          <input type="checkbox" name="keep" value="{{ s.id }}" checked>
        </td>
        <td>
          <textarea data-sid="{{ s.id }}" class="sentence-text">{{ s.sentence }}</textarea>
          <div class="muted">id: {{ s.id }}</div>
        </td>
        <td style="width:160px;">
          <div class="actions">
            <button type="button" class="button save-btn" data-sid="{{ s.id }}">Save</button>
            <button type="button" class="button danger delete-btn" data-sid="{{ s.id }}">Delete</button>
          </div>
        </td>
      </tr>
      {% endfor %}
    </table>
  </form>

  <div style="margin-top:12px;">
    <button id="delete-selected" class="button danger">Delete Selected</button>
  </div>

  <div class="pager">
    {% if page > 1 %}
      <a href="{{ url_for('view_link', link_id=link_id) }}?page={{ page-1 }}" class="button">Prev</a>
    {% endif %}
    {% if page < total_pages %}
      <a href="{{ url_for('view_link', link_id=link_id) }}?page={{ page+1 }}" class="button">Next</a>
    {% endif %}
  </div>

<script>
async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return resp.json();
}

document.querySelectorAll('.save-btn').forEach(btn => {
  btn.addEventListener('click', async (e) => {
    const sid = btn.dataset.sid;
    const ta = document.querySelector('textarea[data-sid="'+sid+'"]');
    const newText = ta.value.trim();
    btn.disabled = true;
    const res = await postJSON('{{ url_for("api_update_sentence") }}', { id: Number(sid), sentence: newText });
    if (res.ok) {
      btn.textContent = 'Saved';
      setTimeout(()=> btn.textContent = 'Save', 1000);
    } else {
      alert('Update failed: ' + (res.error || 'unknown'));
    }
    btn.disabled = false;
  });
});

document.querySelectorAll('.delete-btn').forEach(btn => {
  btn.addEventListener('click', async (e) => {
    const sid = Number(btn.dataset.sid);
    if (!confirm('Delete sentence id ' + sid + '?')) return;
    const res = await postJSON('{{ url_for("api_delete_sentences") }}', { ids: [sid] });
    if (res.ok) {
      // remove row
      const row = document.querySelector('tr[data-sid="'+sid+'"]');
      if (row) row.remove();
    } else {
      alert('Delete failed');
    }
  });
});

document.getElementById('delete-selected').addEventListener('click', async () => {
  const checked = Array.from(document.querySelectorAll('input[name="keep"]:not(:checked)')).map(i => Number(i.value));
  if (checked.length === 0) { alert('No sentences un-checked for delete.'); return; }
  if (!confirm('Delete ' + checked.length + ' sentences?')) return;
  const res = await postJSON('{{ url_for("api_delete_sentences") }}', { ids: checked });
  if (res.ok) {
    checked.forEach(id => {
      const row = document.querySelector('tr[data-sid="'+id+'"]');
      if (row) row.remove();
    });
  } else {
    alert('Delete failed');
  }
});
</script>

</body>
</html>
"""

def render_links_page(links, page, page_size, total_links):
    total_pages = max(1, (total_links + page_size - 1) // page_size)
    start = (page - 1) * page_size + 1
    end = min(total_links, page * page_size)
    return render_template_string(LINKS_TEMPLATE,
                                  links=links, page=page, page_size=page_size,
                                  total_links=total_links, total_pages=total_pages,
                                  start=start, end=end)

def render_link_sentences_page(link_id, link_url, sentences, page, page_size, total):
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size + 1
    end = min(total, page * page_size)
    return render_template_string(LINK_SENTENCES_TEMPLATE,
                                  link_id=link_id, link_url=link_url,
                                  sentences=sentences, page=page, page_size=page_size,
                                  total=total, total_pages=total_pages,
                                  start=start, end=end)

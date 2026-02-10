{% load static %}
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Transcription Jobs</title>

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Zen+Kaku+Gothic+New:wght@400;500;700&display=swap" rel="stylesheet">

  <style>
    :root{
      --bg: #fbfaf9;
      --card: rgba(255,255,255,.86);
      --text: #2b2b2b;
      --muted: #6b6b6b;
      --line: rgba(40,40,40,.10);

      --accent: #c08a7a;
      --accent2: #e6c6c0;
      --accent3: #f3e7e4;

      --shadow: 0 16px 40px rgba(25,25,25,.10);
      --shadow2: 0 10px 22px rgba(25,25,25,.08);

      --radius: 22px;
      --radius2: 16px;

      --focus: 0 0 0 4px rgba(192,138,122,.20);
    }

    *{ box-sizing: border-box; }
    html,body{ height:100%; }
    body{
      margin:0;
      color: var(--text);
      background:
        radial-gradient(900px 500px at 20% 10%, rgba(230,198,192,.35), transparent 60%),
        radial-gradient(900px 500px at 80% 20%, rgba(192,138,122,.22), transparent 55%),
        radial-gradient(900px 500px at 60% 90%, rgba(243,231,228,.70), transparent 55%),
        var(--bg);
      font-family: "Zen Kaku Gothic New", "Inter", system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial, "Noto Sans JP", sans-serif;
      letter-spacing: .02em;
    }

    .wrap{
      min-height:100%;
      display:flex;
      justify-content:center;
      padding: 28px 16px;
    }

    .card{
      width: min(980px, 100%);
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow:hidden;
      backdrop-filter: blur(10px);
    }

    .header{
      padding: 26px 26px 18px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(135deg, rgba(255,255,255,.70), rgba(243,231,228,.55));
    }

    .brand{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap: 14px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }

    .badge{
      display:inline-flex;
      align-items:center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(192,138,122,.25);
      background: rgba(243,231,228,.70);
      color: #553b35;
      font-size: 12px;
      font-weight: 800;
    }
    .dot{
      width:10px; height:10px; border-radius:999px;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(192,138,122,.18);
    }

    h1{
      margin: 0;
      font-size: clamp(22px, 2.2vw, 28px);
      letter-spacing: .03em;
    }
    .sub{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.7;
    }

    .topActions{
      display:flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items:center;
      justify-content:flex-end;
    }

    .btn{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid rgba(192,138,122,.35);
      background: linear-gradient(135deg, rgba(192,138,122,.95), rgba(230,198,192,.95));
      color: #fff;
      font-weight: 800;
      letter-spacing: .03em;
      cursor:pointer;
      box-shadow: var(--shadow2);
      transition: transform .08s ease, filter .15s ease, box-shadow .15s ease;
      text-decoration:none;
      white-space: nowrap;
    }
    .btn:hover{ filter: brightness(1.02); }
    .btn:active{ transform: translateY(1px); }

    .btn-secondary{
      background: rgba(255,255,255,.80);
      color: #5a3e37;
      border: 1px solid rgba(192,138,122,.25);
      box-shadow: none;
    }
    .btn-secondary:hover{
      box-shadow: 0 10px 22px rgba(25,25,25,.06);
    }

    .content{
      padding: 18px 26px 26px;
      display:grid;
      gap: 14px;
    }

    .grid{
      display:grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }

    .jobCard{
      display:block;
      border: 1px solid rgba(40,40,40,.10);
      background: rgba(255,255,255,.78);
      border-radius: 18px;
      padding: 14px 14px;
      text-decoration:none;
      color: inherit;
      box-shadow: 0 10px 22px rgba(25,25,25,.06);
      transition: transform .08s ease, box-shadow .15s ease, border-color .15s ease;
    }
    .jobCard:hover{
      transform: translateY(-1px);
      box-shadow: 0 16px 30px rgba(25,25,25,.10);
      border-color: rgba(192,138,122,.22);
    }

    .row1{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .title{
      font-weight: 900;
      letter-spacing: .02em;
      font-size: 14.5px;
      line-height: 1.4;
      max-width: 100%;
      overflow:hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .meta{
      display:flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items:center;
      justify-content:flex-end;
    }

    .pill{
      display:inline-flex;
      align-items:center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(40,40,40,.10);
      background: rgba(243,231,228,.55);
      color: #553b35;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }
    .pill .miniDot{
      width: 8px; height: 8px;
      border-radius: 999px;
      background: rgba(40,40,40,.35);
    }

    /* status色（上品に） */
    .pill.done{ background: rgba(220,245,230,.70); border-color: rgba(0,0,0,.08); color:#235a3a; }
    .pill.done .miniDot{ background: rgba(45,140,80,.85); }

    .pill.running{ background: rgba(255,240,220,.75); border-color: rgba(0,0,0,.08); color:#6a3e12; }
    .pill.running .miniDot{ background: rgba(220,140,60,.9); }

    .pill.queued{ background: rgba(240,240,245,.80); border-color: rgba(0,0,0,.08); color:#444; }
    .pill.queued .miniDot{ background: rgba(100,100,110,.70); }

    .pill.error{ background: rgba(255,225,225,.75); border-color: rgba(0,0,0,.08); color:#7b1f1f; }
    .pill.error .miniDot{ background: rgba(200,60,60,.9); }

    .row2{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap: 12px;
      margin-top: 10px;
      flex-wrap: wrap;
    }

    .small{
      color: var(--muted);
      font-size: 12.5px;
      line-height: 1.6;
      display:flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items:center;
    }

    .progressWrap{
      flex: 1 1 260px;
      min-width: 220px;
      display:flex;
      align-items:center;
      gap: 10px;
      justify-content:flex-end;
    }

    .bar{
      position: relative;
      height: 10px;
      width: min(360px, 100%);
      border-radius: 999px;
      background: rgba(40,40,40,.10);
      overflow:hidden;
      border: 1px solid rgba(40,40,40,.08);
    }
    .bar > span{
      display:block;
      height:100%;
      width: 0%;
      background: linear-gradient(135deg, rgba(192,138,122,.95), rgba(230,198,192,.95));
      border-radius: 999px;
    }
    .pct{
      font-size: 12px;
      font-weight: 900;
      color: #5a3e37;
      white-space: nowrap;
    }

    .empty{
      border-radius: 18px;
      border: 1px dashed rgba(40,40,40,.18);
      background: rgba(255,255,255,.65);
      padding: 18px 14px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
      text-align:center;
    }

    .footer{
      padding: 14px 26px 20px;
      color: rgba(90,90,90,.75);
      font-size: 12px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap: 10px;
      border-top: 1px solid var(--line);
    }

    @media (max-width: 640px){
      .header, .content, .footer{ padding-left: 16px; padding-right: 16px; }
      .progressWrap{ justify-content: flex-start; }
      .bar{ width: 100%; }
      .title{ white-space: normal; }
    }
  </style>
</head>

<body>
  <div class="wrap">
    <div class="card" role="main" aria-label="Transcription Jobs">
      <div class="header">
        <div class="brand">
          <div>
            <div class="badge"><span class="dot"></span> Transcription</div>
          </div>
          <div class="topActions">
            <a class="btn btn-secondary" href="{% url 'job_create' %}">＋ New Job</a>
            <a class="btn" href="/admin/" target="_blank" rel="noopener">Admin</a>
          </div>
        </div>

        <h1>Transcription Jobs</h1>
        <p class="sub">
          IDは画面に出さず、タイトル（ファイル名）で管理。<br>
          クリックすると詳細（進捗・プレビュー・DL）に移動します。
        </p>
      </div>

      <div class="content">
        {% if jobs %}
          <div class="grid">
            {% for j in jobs %}
              <a class="jobCard" href="{% url 'job_detail' j.id %}">
                <div class="row1">
                  <div class="title">
                    {% if j.input_file %}{{ j.input_file.name }}{% else %}（ファイルなし）{% endif %}
                  </div>

                  <div class="meta">
                    <div class="pill {{ j.status }}">
                      <span class="miniDot"></span>
                      {{ j.status|upper }}
                    </div>
                    {% if j.diarize %}
                      <div class="pill"><span class="miniDot" style="background: rgba(192,138,122,.85);"></span>DIARIZE</div>
                    {% endif %}
                    <div class="pill"><span class="miniDot" style="background: rgba(192,138,122,.65);"></span>{{ j.model_name }}</div>
                    <div class="pill"><span class="miniDot" style="background: rgba(192,138,122,.65);"></span>{{ j.language }}</div>
                    <div class="pill"><span class="miniDot" style="background: rgba(192,138,122,.65);"></span>{{ j.segment_sec }}s</div>
                  </div>
                </div>

                <div class="row2">
                  <div class="small">
                    <span>作成：{{ j.created_at }}</span>
                    {% if j.finished_at %}<span>完了：{{ j.finished_at }}</span>{% endif %}
                  </div>

                  <div class="progressWrap" aria-label="progress">
                    <div class="bar" role="progressbar" aria-valuenow="{{ j.progress }}" aria-valuemin="0" aria-valuemax="100">
                      <span style="width: {{ j.progress }}%;"></span>
                    </div>
                    <div class="pct">{{ j.progress }}%</div>
                  </div>
                </div>
              </a>
            {% endfor %}
          </div>
        {% else %}
          <div class="empty">
            まだジョブがありません。<br>
            <a href="{% url 'job_create' %}" style="color: #5a3e37; font-weight:900; text-decoration: none; border-bottom:1px solid rgba(192,138,122,.5); padding-bottom:2px;">＋ New Job</a>
            から作ってみてね。
          </div>
        {% endif %}
      </div>

      <div class="footer">
        <div>© dj_transcriber</div>
        <div style="opacity:.9;">milk-tea / dusty-rose theme</div>
      </div>
    </div>
  </div>
</body>
</html>

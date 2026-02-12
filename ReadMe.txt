DJ_TRANSCRIBER（README / 設計書）

Django で音声ファイルをアップロードし、バックグラウンドワーカーで **Whisper による文字起こし**＋ **pyannote による話者分離（diarization）** を行い、結果を保存・表示するアプリです。

---

1. 目的

- 音声をアップロードして「文字起こしジョブ」を作成できる
- 重い処理（pyannote / whisper / ffmpeg）を Web から切り離し、**Worker** で非同期に実行する
- 進捗（%）と最終結果テキストを DB に保存し、画面で確認できる

---

2. 機能一覧（現状実装ベース）

Web（Django）
- 音声ファイルのアップロード（`TranscriptionJob` 作成）
- ジョブ一覧表示 / 詳細表示
- ステータス表示：`queued / running / done / error`
- 進捗表示：`progress`（0〜100）
- 結果表示：`output_text`
- エラー表示：`error_message`
- ファイル名表示用：`display_filename`（末尾のランダムっぽいサフィックスを除去して表示）

Worker（management command）
- `status="queued"` のジョブを古い順に 1件取り出して処理
- `status="running"` に更新し、処理開始時刻 `started_at` を保存
- pyannote で話者分離（min 2 / max 4 speakers）
- diarization の各セグメントごとに音声を切り出して Whisper で文字起こし
- 進捗（`progress`）をセグメント処理数に応じて更新
- 完了時に `output_text` を保存し `status="done"` / `finished_at` を保存
- 例外時は `status="error"` / `error_message` / `finished_at` を保存

---

## 3. 技術スタック

- Python / Django
- 文字起こし：`whisper`（`job.model_name` を利用）
- 話者分離：`pyannote.audio`（HuggingFace token 必須）
- 音声変換：`ffmpeg`

---

4. データモデル設計（TranscriptionJob）

`transcribe/models.py`

ステータス
- `queued`：待機中
- `running`：処理中
- `done`：完了
- `error`：失敗

フィールド

| フィールド | 型 | 意味 |
|---|---|---|
| created_at | DateTime (auto) | 作成日時 |
| started_at | DateTime nullable | 処理開始日時（Worker がセット） |
| finished_at | DateTime nullable | 処理終了日時（成功/失敗でセット） |
| status | CharField | queued/running/done/error |
| progress | PositiveInteger | 0〜100 進捗 |
| model_name | CharField | Whisper model 名（default: `small`） |
| segment_sec | PositiveInteger | 分割秒数（default: 600）※現状 worker では未使用 |
| language | CharField | `ja` / `en` / `auto`（default: `ja`） |
| input_file | FileField | アップロード音声（upload_to="input/"） |
| output_text | TextField | 文字起こし結果 |
| error_message | TextField | エラー内容 |
| original_filename | CharField | 元ファイル名（任意） |
| diarize | BooleanField | diarization 実行するか（default True）※現状 worker では未使用 |

表示用プロパティ
- `display_filename`
  - `input_file.name` から basename を取り出し
  - `_<英数字6〜10文字>` の末尾サフィックスを除去して表示（例：`xxx_ab12CD` を削る）

---

5. Worker 設計（transcribe_worker）

`transcribe/management/commands/transcribe_worker.py`

起動時ログ
- `✅ transcribe_worker booted`
- `DATABASE_URL set? True/False`
- `HF_TOKEN set? True/False`

ジョブ取得戦略
- `status="queued"` を `created_at` 昇順で `first()` 取得
- `select_for_update()` + `transaction.atomic()` でロックし二重実行を回避

ステータス更新
- 取得直後：
  - `status="running"`
  - `started_at=now`
  - `progress=0`
  - `error_message=""`

diarization（pyannote）
- `HF_TOKEN` が無い場合は `RuntimeError`
- 入力音声を `audio_16k.wav` に変換（wav/16k/mono）
- `pyannote/speaker-diarization-3.1` を使用
- `min_speakers=2`, `max_speakers=4`
- セグメント構造：`{speaker, start, end}` の配列に整形し start順にソート

whisper 文字起こし
- whisper model は `model_cache` でキャッシュ（同一モデル再ロード回避）
- 各 diarization セグメントについて：
  - `ffmpeg -ss start -t duration` で `seg_###.wav` を作成
  - `model.transcribe()` 実行
  - `language != "auto"` のとき `language` を指定
  - `fp16=False`

output_text フォーマット
- 1行 = 1発話（セグメント）
- 形式：`[SPEAKER_XX]: テキスト`
- 全行を `\n` で結合して `job.output_text` に保存

進捗更新
- `progress = int(idx * 100 / total)`
- セグメント処理ごとに DB へ保存（`update_fields=["progress"]`）

正常終了
- `status="done"`
- `progress=100`
- `finished_at=now`

例外
- `status="error"`
- `error_message = "{例外クラス名}: {メッセージ}"`
- `finished_at=now`

---

6. ファイル保存設計

- アップロード音声：`media/input/` 配下（Django FileField の upload_to="input/"）
- Worker 作業ディレクトリ：
  - `input_file` と同じディレクトリ配下に `job_{id}_chunks/`
  - 内部生成物：
    - `audio_16k.wav`
    - `seg_###.wav`（各セグメント）

---

7. 環境変数

必須（環境により）
- `HF_TOKEN`（pyannote を使う場合は必須）
- `DATABASE_URL`（本番運用でDBを切り替える場合）

`.env` 例：
```env
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=1
DATABASE_URL=sqlite:///db.sqlite3

HF_TOKEN=xxxxxxxxxxxxxxxxxxxx

8. ローカル起動手順
8.1 依存（ffmpeg）

macOS:

brew install ffmpeg

8.2 Python 依存
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

8.3 DB
python manage.py migrate

8.4 Web 起動
python manage.py runserver

8.5 Worker 起動（別ターミナル）
python manage.py transcribe_worker

9. 注意点（現状の仕様ギャップ）

TranscriptionJob.diarize があるが、worker 側で参照していないため 現状は常に diarization を実行します。

TranscriptionJob.segment_sec があるが、worker 側は split_audio() を定義しているものの 現状のメイン処理では未使用です。

将来的に「長尺音声を一定秒数で切ってWhisper」等に拡張可能。

10. トラブルシューティング

1.queued のまま進まない
　・Worker が起動していない可能性が最有力
　・DB が本番で揮発（SQLite）しておりジョブが消えている可能性もある

2.HF_TOKEN missing
   .env / 環境変数に HF_TOKEN をセット
    確認：echo $HF_TOKEN

3.ffmpeg not found
   ・ffmpeg -version が通るか確認
　　・PATH 設定を見直す

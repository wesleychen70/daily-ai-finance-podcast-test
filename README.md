# 每日 AI 財經 Podcast 自動化系統（測試階段）

Python + Gemini API + GitHub Actions + Releases + Pages。**只有測試頻道，沒有正式節目發布或 Spotify 提交。**

## 執行

Python 3.12，`python -m pip install -r requirements.txt`。複製 `.env.example` 為 `.env` 並填金鑰。

```powershell
python -m unittest discover -s tests -v
python -m podcast preflight
python -m podcast collect
python -m podcast generate
```

此電腦可使用 `powershell -File scripts/run.ps1 generate`，會使用已安裝的專案依賴。
產物在 `build/台灣日期/`：episode.mp3、transcript.txt、sources.json、script.json、
editorial-check.json、audio-check.json、manifest.json、status.json 與原始來源快照。

## 驗證門檻

1. 來源有網址、抓取時間、資料日期、原始快照 SHA-256。缺美股、台股、全球市場、總經、科技、全球新聞、VIX、官方行事曆任一類就停止。
2. 新聞以七日內為限，行情五日內以容許週末與假日。逐項明示資料日；這不是交易所假日推算器，長假可能停止產出。
3. 六主題、4800–6800 個中文字；每段來源 ID 與原文證據片段。資料指令不能控制系統。
4. 第二次獨立上下文的模型審查每段事實，問題清單必須為空。
5. Gemini 3.8 TTS 以章節生成，每段最多 1400 字元，超長章節按句子拆段；MP3 128 kbps、44.1 kHz、單聲道，合併後響度目標 -16 LUFS、峰值 -1.5 dBTP；以不超過 15% 的語速調整接近 20 分鐘，仍超出時長門檻就拒絕。
6. 每段實際音訊再送模型轉錄，與稿件相似度至少 93%，並檢查台灣國語、異常、漏讀。整集 18–23 分鐘，完全解碼後才產生 VERIFIED_TEST manifest。
7. 發布前檢查音檔、稿件、來源及查核結果雜湊；RSS 僅接受 VERIFIED_TEST。
8. Releases 公開檔以**未登入** HEAD、完整 GET、SHA-256、Range GET (206 / Content-Range) 實測後才進 RSS。

模型輔助的事實與口音檢查有誤判風險，不能等同真人聽審或保證零錯誤。
`human_listening: NOT_RUN` 與 `spotify_ingestion: NOT_RUN` 會保留，直到有真實證據。

## 來源與範圍

- 台股：TWSE OpenAPI MI_INDEX。
- 美股與全球指數：Yahoo Finance 公開 chart endpoint；是非正式 API、無可用性保證，可能延遲或失效。
- VIX：CBOE 官方每日 CSV；不是方向預測或完整市場情緒指標。
- 總經：Federal Reserve、BLS RSS、FRED（若可取得）、CNBC economy；指數水準不可當通膨率。
- 科技：NVIDIA、Microsoft 官方 RSS、CNBC technology；未取得可靠財報就明說。
- 全球：ECB、CNBC world。
- 當日事件：BLS 官方 iCalendar，無法取得時使用聯準會官方行事曆；不是完整的全球事件清單。
- RSS 摘要只支持其標題與摘要的事實，不能暗稱已讀過全文。

## 雲端部署

`scripts/bootstrap.py` 以已登入的 GitHub CLI 建立公開 **test** 專案、上傳原始碼、
設定 Gemini secret、Pages 與每日排程，不啟用任何計費。

Repository secret：`GEMINI_API_KEY`。
Repository variables：`PIPELINE_ENABLED=true`、`PUBLIC_TEST_ENABLED=true`、`PAGES_BASE_URL=https://帳號.github.io/專案`。

台灣時間 05:17 主跑；06:07、06:32 補跑。相同台灣日期 GUID 固定，已發 RSS 則跳過。
HTTP 暫時錯誤重試最多三次。每日語音快取、API 請求上限（保守預留含重試共 210 次）、
失敗狀態與 7 日 Actions 驗證產物會保存。06:55 停止新增排程 API 請求；06:58 後不更新 RSS。
GitHub 排程可能延遲或漏跑，因此無法保證 07:00；Spotify 抓取另有延遲。
公開庫排程 60 日無活動會停用；成功發布會提交 feed 更新。連續失敗時須從 Actions 通知處理。

Releases 相容性失敗時，先把 MP3 部署到 Pages、保留原 RSS，再實測 Pages 媒體網址，通過後才更新 RSS。
Pages 備援只保留最近 20 集，避免超出站台大小；不是無限音訊庫。舊集會退出 RSS；若要保留全部舊集，
需要另行核准外部儲存。部署或媒體檢查失敗時不宣稱可被 Spotify 抓取。

RSS：`/rss-test.xml`。測試首頁標記 noindex，RSS `itunes:block=Yes`，不提交任何目錄。
這只能降低被目錄收錄的機會；測試網址及 Releases 本身是公開的。

## 費用與正式啟用

只使用使用者已有的 API 金鑰，不開通付費。API 金鑰本身無法證明專案是否綁定計費，
使用者須確認免費專案；配額不足就停止，絕不切換到付費帳號。模型可透過
`GEMINI_TEXT_MODEL`、`GEMINI_TTS_MODEL` 設定，預設 gemini-3.5-flash-lite 與 gemini-3.8-flash-lite-tts。
模型供應商可能調整可用性、免費配額或價格。

正式節目須使用者另行批准：正式節目名與封面、公開聯絡 email、真人試聽、
解除目錄阻擋、Spotify for Creators 登入與 RSS 所有權驗證。沒有 Spotify 真實讀取結果前，
HTTP 相容性通過也不能稱為 Spotify 已驗證或已收錄。

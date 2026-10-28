# 每日 AI 財經 Podcast：測試部署結果

報告日期：2026-10-29，Asia/Taipei。這是測試頻道，尚未提交正式 Spotify 節目。

## 可使用的產物

- [試播聆聽頁](https://wesleychen70.github.io/daily-ai-finance-podcast-test/)
- [公開 MP3，20 分鐘](https://wesleychen70.github.io/daily-ai-finance-podcast-test/media/test-2026-10-28.mp3)
- [RSS](https://wesleychen70.github.io/daily-ai-finance-podcast-test/rss-test.xml)
- [逐字稿與來源、驗證附件](https://github.com/wesleychen70/daily-ai-finance-podcast-test/releases/tag/test-2026-10-28)
- [GitHub 專案](https://github.com/wesleychen70/daily-ai-finance-podcast-test)
- [完整雲端續跑／部署成功記錄](https://github.com/wesleychen70/daily-ai-finance-podcast-test/actions/runs/40708846166)

試播集日期為 **2026-10-28**；新聞資料截止為 **2026-10-28 21:28（台灣時間）**，不是 10/29 的新節目。
官方人名對照另依世界銀行人物介紹核對，不作為截止時間後的新財經消息。

## 實測結果

| 項目 | 結果與證據邊界 |
| --- | --- |
| 自動化程式驗證 | 20 項測試通過，包含來源日期、缺漏、引用、快照雜湊、XML、媒體 Range、核准覆蓋率、快取綁定與 ZIP 安全 |
| 真實來源收集 | 52 筆證據，附網址、時間、原始快照及 SHA-256；包含一筆官方人名對照 |
| 六大主題稿件 | 5017 個中文字，18 段均有引用並通過逐段模型審查 |
| Gemini 實際語音 | 六段最終音訊均經實際轉錄，最低文字相似度約 94.2%；另通過數字、日期、方向、單位、名稱忠實度檢查 |
| 試播音訊編輯 | 最後一段用既有 Gemini 音訊移除被拒絕部分並接上已驗證的同聲線結尾，重新通過全部檢查；未用其他 TTS 冒充 |
| 最終 MP3 | 雲端實際合併、正規化、重新編碼與完整解碼；1200.01 秒、19,200,670 bytes |
| 公開音檔可讀性 | 未登入 HEAD 200、完整 GET、Range GET 206／Content-Range 及 SHA-256 全通過 |
| Releases | 音檔與證據已儲存；公開下載實測回傳 application/octet-stream，因此未直接採作 RSS enclosure |
| 媒體備援 | 實際切換 GitHub Pages；公開 MIME 為 audio/mp3，RSS enclosure 宣告 audio/mpeg，完整檔雜湊一致 |
| RSS 與 Pages | 公網 HTTP 200、讀回一集正確 GUID；雲端部署與最終 RSS 檢查成功 |
| Spotify RSS | 已登入並實際讀到節目標題、作者、說明；官方表單明確指出缺電子郵件地址 |
| Spotify 所有權與實際音檔收錄 | **尚未完成**：需使用者提供同意公開於 RSS 的 email，並完成 Spotify 所有權認證；不宣稱 MP3 已被 Spotify 收錄 |
| 真人試聽 | **NOT_RUN**；模型通過不等同人類確認口音與內容完全正確 |
| 從零生成整集的雲端冷啟動 | **NOT_RUN**：首次完整雲端測試使用已實際產生並驗證的同日 checkpoint；資料收集、Gemini TTS 與模型查核已在本機實跑 |
| 每日定時觸發 | 排程已部署且 active；首次真實晨間排程成功尚待觀察，不能當作已驗證 |

公網 MP3 的 SHA-256：

```text
efff97d9fb2d6ccff1ccebaf08f68272f248cc5e11a4199029e586145e6bca5b
```

本機編碼檔與雲端重新編碼檔的位元組不同；以上雜湊指向實際 RSS 使用的公網檔。
各自的 manifest 與驗證記錄有分別保留，未將兩者的雜湊混用。

## 排程、限制與發布界線

每天台灣時間 **05:17** 主跑，**06:07、06:32** 補跑。GitHub Actions 在雲端執行，不需要此電腦開機。
暫時網路錯誤會重試，已通過且輸入雜湊相同的審核與語音會重用；來源不完整、稿件或音訊不合格就保留上一集。
06:55 停止新增排程 API 請求，06:58 後不更新 RSS。
[GitHub 排程可能延遲](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)，不能保證每天 07:00 前完成或 Spotify 同時更新。

未開通任何付費服務。測試專案的 Gemini TTS 免費上限實測為每日 10 次；正常一集目標約 6–7 次。
10/28 測試曾耗盡免費額度，供應商當時回報約 10/29 15:00 重置，故 10/29 晨間新集可能受阻。
試播未取得的部分總經系列在口播中有明講；另一次官方 CPI 表格擷取測試成功，未回填為凍結試播稿中的新事實。

Pages 備援目前採最近 **20 集**的滾動 RSS／媒體，所有原始測試 MP3 與證據留在 Releases。
若要全部歷史集數都持續透過 RSS 播放，需要另行確認長期媒體儲存方案。

RSS 保留 `itunes:block=Yes` 與測試名稱，未提交正式節目、未公開聯絡 email，也未改動既有 Spotify 節目。
Spotify 截圖保存在本機 `artifacts/spotify-rss-email-required.png`；原始讀回與雜湊證據保存在本機 `artifacts/`。

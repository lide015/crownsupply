// Gold Trader LITE Service Worker —— 只為了滿足瀏覽器「可安裝成 App」的技術要求（PWA
// 可安裝性需要一個已註冊、帶 fetch 事件監聽器的 service worker）。
//
// 刻意**不呼叫** event.respondWith()：瀏覽器的可安裝判定只看「有沒有註冊 fetch 監聽器」，
// 不要求真的攔截或提供任何回應——不呼叫 respondWith() 的話，每個請求就完全交由瀏覽器
// 原生處理，這個 service worker 實質上不插手任何一個請求。這是刻意的保守選擇：
// 1. 這是即時報價/訊號的交易輔助工具，離線快取秀出舊資料會誤導使用者以為那是最新
//    狀態，不安全（跟這個系統其他地方「重點資訊要正確」的一貫立場一致）。
// 2. 曾經試過用 respondWith(fetch(event.request)) 做「純轉發、不快取」，結果發現這樣
//    會讓每個請求都先繞經 service worker 這層再送出，在某些自動化測試/網路模擬工具下
//    行為會跟預期不一致（見這次修正的討論）——完全不呼叫 respondWith 才是真正意義上
//    「不介入」，不是「介入但轉發」。
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", () => {
  // 刻意留空，不呼叫 respondWith()。
});

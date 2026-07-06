// Content script for YouTube matching pages

// Listen for message from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "get_youtube_info") {
    let title = "";
    let artist = "";

    try {
      // 1. Try to find the primary title element on the watch page
      let titleEl = document.querySelector('h1.ytd-watch-metadata yt-formatted-string') || 
                    document.querySelector('h1.ytd-watch-metadata') ||
                    document.querySelector('h1.title.ytd-video-primary-info-renderer');
      
      if (titleEl) {
        title = titleEl.textContent.trim();
      } else {
        // Fallback to page title
        title = document.title.replace(" - YouTube", "").trim();
      }

      // 2. Try to find the channel (artist) name
      let channelEl = document.querySelector('#owner #channel-name a') ||
                      document.querySelector('ytd-video-owner-renderer #channel-name a') ||
                      document.querySelector('yt-formatted-string.ytd-channel-name a');
                      
      if (channelEl) {
        artist = channelEl.textContent.trim();
      } else {
        artist = "Unknown Channel";
      }
    } catch (e) {
      console.error("Error scraping YouTube metadata:", e);
    }

    sendResponse({ 
      title: title || "Unknown Title", 
      artist: artist || "Unknown Artist", 
      url: window.location.href 
    });
  }
  return true;
});

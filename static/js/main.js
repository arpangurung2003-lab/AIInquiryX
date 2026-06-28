const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

document.addEventListener("DOMContentLoaded", () => {
  const menuBtn = document.getElementById("menuBtn");
  const navLinks = document.getElementById("navLinks");
  if (menuBtn && navLinks) {
    menuBtn.addEventListener("click", () => navLinks.classList.toggle("open"));
  }
const eyeIcon = `
  <svg viewBox="0 0 24 24" width="21" height="21" fill="none" aria-hidden="true">
    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"
      stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="12" cy="12" r="3"
      stroke="currentColor" stroke-width="2"/>
  </svg>
`;

const eyeOffIcon = `
  <svg viewBox="0 0 24 24" width="21" height="21" fill="none" aria-hidden="true">
    <path d="M3 3l18 18"
      stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    <path d="M10.6 10.6A3 3 0 0 0 13.4 13.4"
      stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    <path d="M9.9 5.2A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17.4 17.4 0 0 1-3.2 4.2"
      stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M6.1 6.8C3.4 8.6 2 12 2 12s3.5 7 10 7c1.5 0 2.8-.3 4-.8"
      stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
`;

document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
  const input = document.querySelector(btn.getAttribute("data-toggle-password"));
  const icon = btn.querySelector(".eye-icon") || btn;

  icon.innerHTML = eyeIcon;

  btn.addEventListener("click", () => {
    if (!input) return;

    const isHidden = input.type === "password";
    input.type = isHidden ? "text" : "password";

    btn.setAttribute(
      "aria-label",
      isHidden ? "Hide password" : "Show password"
    );

    icon.innerHTML = isHidden ? eyeOffIcon : eyeIcon;
  });
});

  document.querySelectorAll("[data-loading-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      form.classList.add("is-loading");
      const submit = form.querySelector('button[type="submit"], button:not([type])');
      if (submit) {
        const label = submit.querySelector(".btn-label");
        submit.disabled = true;
        submit.setAttribute("aria-busy", "true");
        if (label) {
          label.dataset.originalText = label.textContent;
          label.textContent = "Submitting...";
        } else {
          submit.dataset.originalText = submit.textContent;
          submit.textContent = "Processing...";
        }
      }
    });
  });

  const footerBackTop = document.getElementById("footerBackTop");
  if (footerBackTop) footerBackTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

  const countNumbers = document.querySelectorAll(".count-number");
  const runCounter = (counter) => {
    const target = Number(counter.dataset.count || 0);
    const suffix = counter.dataset.suffix || "";
    const duration = 1400;
    const startTime = performance.now();
    const update = (currentTime) => {
      const progress = Math.min((currentTime - startTime) / duration, 1);
      const value = Math.floor(progress * target);
      counter.textContent = value + suffix;
      if (progress < 1) requestAnimationFrame(update);
      else counter.textContent = target + suffix;
    };
    requestAnimationFrame(update);
  };

  if ("IntersectionObserver" in window) {
    const counterObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          runCounter(entry.target);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.4 });
    countNumbers.forEach((counter) => counterObserver.observe(counter));

    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll(".card, .showcase-tile, .admin-card, .modern-panel, .result-card, .form-card, .contact-panel, .gallery-card, .blog-card").forEach((el, index) => {
      el.classList.add("reveal-on-scroll");
      el.style.setProperty("--stagger", `${Math.min(index % 8, 7) * 55}ms`);
      revealObserver.observe(el);
    });
  } else {
    countNumbers.forEach(runCounter);
  }

  document.querySelectorAll(".dashboard-js-height, .modern-bar-chart .chart-bar").forEach((bar) => {
    const height = parseFloat(bar.dataset.height || "8");
    bar.style.height = `${Math.max(8, Math.min(height, 100))}%`;
  });

  initChatbot();
  initAdminAI();
  initAdminNotifications();
  initReviewCarousel();
});

function initChatbot() {
  const chatToggle = document.getElementById("chatToggle");
  const chatPanel = document.getElementById("chatPanel");
  const chatClose = document.getElementById("chatClose");
  const chatBody = document.getElementById("chatBody");
  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");

  if (chatToggle && chatPanel) chatToggle.addEventListener("click", () => chatPanel.classList.toggle("open"));
  if (chatClose && chatPanel) chatClose.addEventListener("click", () => chatPanel.classList.remove("open"));

  const addChatMessage = (message, type = "bot") => {
    if (!chatBody) return;
    const div = document.createElement("div");
    div.className = `chat-message ${type === "user" ? "user-msg" : "bot-msg"}`;
    div.textContent = message;
    chatBody.appendChild(div);
    chatBody.scrollTop = chatBody.scrollHeight;
    return div;
  };

  const askBot = async (text) => {
    const loading = addChatMessage("", "bot");
    if (loading) {
      loading.classList.add("typing-dots");
      loading.innerHTML = "<span></span><span></span><span></span>";
    }
    try {
      const response = await fetch("/chatbot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text })
      });
      const data = await response.json();
      if (loading) {
        loading.classList.remove("typing-dots");
        loading.textContent = data.reply || "I could not generate a reply right now.";
      }
    } catch (error) {
      if (loading) {
        loading.classList.remove("typing-dots");
        loading.textContent = "Chat service is unavailable. You can still submit or track an inquiry from the navigation.";
      }
    }
  };

  if (chatForm && chatInput) {
    chatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = chatInput.value.trim();
      if (!text) return;
      addChatMessage(text, "user");
      chatInput.value = "";
      askBot(text);
    });
  }

  document.querySelectorAll(".quick-replies button[data-msg]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const text = btn.dataset.msg;
      if (!text) return;
      if (chatPanel) chatPanel.classList.add("open");
      addChatMessage(text, "user");
      askBot(text);
    });
  });
}

function initAdminAI() {
  const aiText = document.getElementById("aiResultText");
  const aiCard = document.getElementById("aiResultCard");
  const aiType = document.getElementById("aiResultType");
  const aiModal = document.getElementById("aiGlobalModal");
  const aiModalText = document.getElementById("aiModalText");
  const aiModalType = document.getElementById("aiModalType");
  const adminResponseBox = document.getElementById("adminResponseBox");

  const showAIResult = (type, output) => {
    const label = type ? type.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "AI Result";
    if (aiCard && aiText) {
      aiCard.hidden = false;
      aiText.value = output || "";
      if (aiType) aiType.textContent = label;
      aiCard.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (aiModal && aiModalText) {
      aiModal.hidden = false;
      aiModalText.value = output || "";
      if (aiModalType) aiModalType.textContent = label;
    }
  };

  document.querySelectorAll("[data-ai-action][data-url]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Generating...";
      try {
        const response = await fetch(btn.dataset.url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CSRFToken": csrfToken()
          },
          body: JSON.stringify({ action: btn.dataset.aiAction })
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || "AI request failed");
        showAIResult(data.type || btn.dataset.aiAction, data.output || "");
      } catch (error) {
        showAIResult("AI Error", error.message || "AI request failed. Check your API key and dependencies.");
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  });

  const copyText = async (source) => {
    if (!source) return;
    source.select();
    try { await navigator.clipboard.writeText(source.value); }
    catch { document.execCommand("copy"); }
  };
  document.getElementById("copyAiBtn")?.addEventListener("click", () => copyText(aiText));
  document.getElementById("copyAiModalBtn")?.addEventListener("click", () => copyText(aiModalText));
  document.getElementById("useAiReplyBtn")?.addEventListener("click", () => {
    if (adminResponseBox && aiText) adminResponseBox.value = aiText.value;
  });
  document.getElementById("aiModalClose")?.addEventListener("click", () => { if (aiModal) aiModal.hidden = true; });
}

function initAdminNotifications() {
  const bell = document.getElementById("notificationBell");
  const dropdown = document.getElementById("adminNotificationDropdown");
  const unreadText = document.getElementById("notificationUnreadText");

  const markNotificationsRead = async () => {
    try {
      const response = await fetch("/admin/notifications/mark-read", {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "X-CSRFToken": csrfToken()
        }
      });

      if (response.ok) {
        document.querySelectorAll(".notification-count").forEach((el) => el.remove());
        if (unreadText) unreadText.textContent = "0";
      }
    } catch {
      /* keep page working even if request fails */
    }
  };

  if (bell && dropdown) {
    bell.addEventListener("click", async (event) => {
      event.stopPropagation();

      const shouldOpen = dropdown.hidden;
      dropdown.hidden = !shouldOpen;
      bell.setAttribute("aria-expanded", shouldOpen ? "true" : "false");

      if (shouldOpen) {
        await markNotificationsRead();
      }
    });

    dropdown.addEventListener("click", (event) => {
      event.stopPropagation();
    });

    document.addEventListener("click", () => {
      dropdown.hidden = true;
      bell.setAttribute("aria-expanded", "false");
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        dropdown.hidden = true;
        bell.setAttribute("aria-expanded", "false");
      }
    });
  }

  document.querySelectorAll("[data-mark-notifications]").forEach((btn) => {
    btn.addEventListener("click", markNotificationsRead);
  });

  document.querySelectorAll("[data-delete-notification]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const url = btn.getAttribute("data-delete-notification");
      const item = btn.closest("[data-notification-item]");

      if (!url) return;

      try {
        const response = await fetch(url, {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "X-CSRFToken": csrfToken()
          }
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
          throw new Error(data.error || "Could not delete notification");
        }

        if (item) item.remove();

        const remaining = document.querySelectorAll("[data-notification-item]").length;
        const list = document.querySelector(".notification-dropdown-list");

        if (remaining === 0 && list) {
          list.innerHTML = `
            <article class="admin-notification-empty">
              <b>No notifications</b>
              <small>Your notification inbox is clear.</small>
            </article>
          `;
        }

        if (typeof data.unread_count !== "undefined" && unreadText) {
          unreadText.textContent = String(data.unread_count);
        }
      } catch (error) {
        alert(error.message || "Notification delete failed.");
      }
    });
  });
}

function initReviewCarousel() {
  const cards = Array.from(document.querySelectorAll(".clean-review-card"));
  const thumbs = Array.from(document.querySelectorAll(".clean-thumb"));
  const prev = document.getElementById("cleanReviewPrev");
  const next = document.getElementById("cleanReviewNext");
  if (!cards.length || !thumbs.length || !prev || !next) return;
  let current = Math.max(0, cards.findIndex(card => card.classList.contains("is-active")));
  const show = (i) => {
    cards[current]?.classList.remove("is-active");
    thumbs[current]?.classList.remove("is-active");
    current = (i + cards.length) % cards.length;
    cards[current]?.classList.add("is-active");
    thumbs[current]?.classList.add("is-active");
  };
  thumbs.forEach((thumb, i) => thumb.addEventListener("click", () => show(i)));
  prev.addEventListener("click", () => show(current - 1));
  next.addEventListener("click", () => show(current + 1));
}

/**
 * Documentr — Shared Authentication Telemetry Helper
 *
 * Intercepts window.fetch and injects a password validation modal
 * if ACCESS_PASSWORD is set on the backend.
 */

(function() {
    // 1. Define UI Modal HTML
    const modalHtml = `
    <div class="modal-overlay" id="auth-modal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; justify-content: center; align-items: center; z-index: 100000; background: rgba(10, 10, 15, 0.85); backdrop-filter: blur(12px); font-family: system-ui, -apple-system, sans-serif;">
        <div class="modal" style="max-width: 380px; width: 100%; border: 1px solid rgba(255,255,255,0.08); background: #181824; border-radius: 12px; padding: 28px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); display: flex; flex-direction: column; gap: 14px; color: #f8fafc; box-sizing: border-box;">
            <div style="font-size: 36px; text-align: center; line-height: 1;">🔒</div>
            <h2 style="text-align: center; margin: 0; padding: 0; border: none; font-size: 18px; color: #f8fafc; font-weight: 700; background: transparent;">Access Password Required</h2>
            <p style="font-size: 12px; color: #94a3b8; text-align: center; margin: 0; line-height: 1.5; font-weight: 400;">This Documentr instance is protected. Please enter the access password to continue.</p>
            <div id="auth-error-msg" style="color: #ef4444; font-size: 11px; text-align: center; font-weight: 600; display: none;">❌ Invalid password. Please try again.</div>
            <input type="password" id="auth-password-input" placeholder="Enter password..." style="width: 100%; padding: 10px 12px; border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; background: #0f0f15; color: #f8fafc; text-align: center; outline: none; font-size: 14px; box-sizing: border-box;" />
            <button id="btn-submit-auth" style="width: 100%; padding: 10px; border: none; font-weight: bold; background: #6366f1; color: white; border-radius: 6px; cursor: pointer; font-size: 14px; transition: background 0.2s;">Authenticate</button>
        </div>
    </div>
    `;

    // 2. Inject modal into body on load
    function injectModal() {
        if (document.getElementById('auth-modal')) return;
        const div = document.createElement('div');
        div.innerHTML = modalHtml.trim();
        document.body.appendChild(div.firstChild);
    }

    if (document.body) {
        injectModal();
    } else {
        document.addEventListener('DOMContentLoaded', injectModal);
    }

    // 3. Password prompt promise
    let authPromiseResolve = null;
    window.promptForPassword = function(showError = false) {
        return new Promise((resolve) => {
            const modal = document.getElementById('auth-modal');
            const errorMsg = document.getElementById('auth-error-msg');
            const input = document.getElementById('auth-password-input');
            const btn = document.getElementById('btn-submit-auth');
            
            if (!modal) {
                // Fallback to prompt() if modal not in DOM yet
                const pass = prompt(showError ? "Invalid password. Enter access password:" : "Enter access password:");
                if (pass) localStorage.setItem('documentr_access_password', pass);
                resolve(pass);
                return;
            }
            
            modal.style.display = 'flex';
            errorMsg.style.display = showError ? 'block' : 'none';
            input.value = '';
            input.focus();
            
            authPromiseResolve = resolve;
            
            const submit = () => {
                const val = input.value.trim();
                if (val) {
                    localStorage.setItem('documentr_access_password', val);
                    modal.style.display = 'none';
                    resolve(val);
                }
            };
            
            btn.onclick = submit;
            input.onkeydown = (e) => {
                if (e.key === 'Enter') submit();
            };
        });
    };

    // 4. Wrap window.fetch
    const originalFetch = window.fetch;
    window.fetch = async function(resource, options = {}) {
        options.headers = options.headers || {};
        const savedPassword = localStorage.getItem('documentr_access_password');
        
        const setHeader = (pass) => {
            if (options.headers instanceof Headers) {
                options.headers.set('X-Access-Password', pass);
            } else if (Array.isArray(options.headers)) {
                // Remove existing X-Access-Password
                options.headers = options.headers.filter(h => h[0] !== 'X-Access-Password');
                options.headers.push(['X-Access-Password', pass]);
            } else {
                options.headers['X-Access-Password'] = pass;
            }
        };

        if (savedPassword) {
            setHeader(savedPassword);
        }

        // Support password query parameter for file exports
        if (typeof resource === 'string' && resource.includes('/export/')) {
            const separator = resource.includes('?') ? '&' : '?';
            if (savedPassword && !resource.includes('password=')) {
                resource = `${resource}${separator}password=${encodeURIComponent(savedPassword)}`;
            }
        }

        let response = await originalFetch(resource, options);

        if (response.status === 401) {
            // Check if auth is required
            let data = {};
            try {
                data = await response.clone().json();
            } catch (e) { /* ignore */ }

            if (data.auth_required) {
                const password = await window.promptForPassword(true);
                if (password) {
                    setHeader(password);
                    // Update URL password param if applicable
                    if (typeof resource === 'string' && resource.includes('/export/')) {
                        resource = resource.replace(/password=[^&]*/, `password=${encodeURIComponent(password)}`);
                    }
                    return originalFetch(resource, options);
                }
            }
        }

        return response;
    };

    // 5. Initial auth check
    async function checkAuthStatus() {
        try {
            const res = await originalFetch('/api/auth/status');
            if (res.ok) {
                const status = await res.json();
                if (status.required && !localStorage.getItem('documentr_access_password')) {
                    await window.promptForPassword(false);
                }
            }
        } catch (e) {
            console.error('Failed to check auth status:', e);
        }
    }

    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        checkAuthStatus();
    } else {
        document.addEventListener('DOMContentLoaded', checkAuthStatus);
    }
})();

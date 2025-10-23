import os, re, time, sys, string, logging
from secrets import choice as schoice
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    ElementClickInterceptedException,
)
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.action_chains import ActionChains

# ========= LOGGING =========
LOG_DIR = "/app/debug"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, "createuser.log")

handlers = [
    logging.StreamHandler(sys.stdout),
    logging.FileHandler(log_file, encoding="utf-8"),
]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=handlers,
)
log = logging.getLogger("createuser")

# ========= ENV =========
CPANEL_URL   = os.getenv("CPANEL_URL", "https://cpanel.example.com")
CPANEL_USER  = os.getenv("CPANEL_USER")
CPANEL_PASS  = os.getenv("CPANEL_PASS")

DOMAIN       = os.getenv("DOMAIN", "")             # contoh: "mbtech.info" (kosong = pakai default di UI)
EMAIL_PREFIX = os.getenv("EMAIL_PREFIX", "akun")   # akun -> akun001, akun002, ...
COUNT        = int(os.getenv("COUNT", "3"))        # jumlah akun yang dibuat
#PASSWORD_STATIC = os.getenv("PASSWORD_STATIC", "") # kalau kosong → generate acak
PASSWORD_STATIC = "@MBtech123" # kalau kosong → generate acak

# ========= UTIL =========
ALPH = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
def gen_pass(n=14): return "".join(schoice(ALPH) for _ in range(n))

def waitx(driver, sec=25): return WebDriverWait(driver, sec)

def _text_of(el: WebElement) -> str:
    try:
        return (el.text or "").strip()
    except Exception:
        return ""

def _short(el: WebElement, maxlen=120) -> str:
    t = _text_of(el)
    if len(t) > maxlen:
        t = t[:maxlen] + "…"
    try:
        tag = el.tag_name
    except Exception:
        tag = "?"
    return f"<{tag}> {t}"

@contextmanager
def try_all_frames(driver):
    """Coba cari elemen di default content & semua iframe."""
    driver.switch_to.default_content()
    yield
    ifr = driver.find_elements(By.TAG_NAME, "iframe")
    if not ifr:
        return
    for f in ifr:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(f)
            yield
        except Exception:
            continue
    driver.switch_to.default_content()

# ========= JS HELPERS =========
def _js_set_value(driver, el, value: str):
    driver.execute_script("""
        const el = arguments[0], val = arguments[1];
        const last = el.value;
        el.focus();
        el.value = val;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
    """, el, value)

def _wait_angular_ready(driver, timeout=30):
    wait = WebDriverWait(driver, timeout)
    # container ng-view ada
    wait.until(lambda d: d.execute_script("return !!document.querySelector('#viewContent')"))
    # Angular idle (kalau ada)
    try:
        wait.until(lambda d: d.execute_script("return !!window.angular"))
        wait.until(lambda d: d.execute_script("""
            try {
                var el = document.querySelector('#viewContent');
                var inj = window.angular && window.angular.element(el).injector && window.angular.element(el).injector();
                if (!inj) return true;
                var $http = inj.get('$http');
                return $http.pendingRequests.length === 0;
            } catch(e){ return true; }
        """))
    except TimeoutException:
        pass

# ========= READY CHECK & DIAGNOSIS =========
def wait_create_button_ready(driver, timeout=30):
    """
    Tunggu tombol Create 'cukup siap':
    - element ada & terlihat
    - tidak disabled stabil selama ~0.5s
    (lebih toleran terhadap overlay/validator yang lambat)
    """
    end = time.time() + timeout
    last_ok = 0
    while time.time() < end:
        ok = driver.execute_script("""
            const btn = document.getElementById('btnCreateEmailAccount');
            if(!btn) return false;
            const visible = btn.offsetParent !== null;
            const disabled = !!btn.disabled || getComputedStyle(btn).pointerEvents === 'none';
            return visible && !disabled;
        """)
        if ok:
            if last_ok == 0:
                last_ok = time.time()
            if time.time() - last_ok >= 0.5:
                return True
        else:
            last_ok = 0
        time.sleep(0.1)
    raise TimeoutException("Create button not ready in time")

def _dump_create_button_diagnostics(driver, tag="btn_diag"):
    try:
        info = driver.execute_script("""
            const btn = document.getElementById('btnCreateEmailAccount');
            const al = document.querySelector('cp-alert-list');
            const ov = document.getElementById('page-overlay');
            return {
                exists: !!btn,
                visible: btn ? (btn.offsetParent !== null) : false,
                disabled: btn ? !!btn.disabled : null,
                pointerNone: btn ? (getComputedStyle(btn).pointerEvents==='none') : null,
                outer: btn ? btn.outerHTML : null,
                overlay: ov ? {display:getComputedStyle(ov).display, opacity:getComputedStyle(ov).opacity} : null,
                hash: location.hash,
                alerts: al ? al.innerText : null
            };
        """)
        log.warning("Create button diag (%s): %s", tag, info)
    except Exception as e:
        log.warning("Diag error (%s): %s", tag, e)

# ========= LOGIN & TOKEN =========
def login_and_get_token_base(driver, wait) -> str:
    """
    Login ke /login/, tunggu redirect ke URL bertoken:
    Contoh: https://cpanel.host.tld/cpsess0620021535/
    """
    log.info("Open login page… %s", CPANEL_URL)
    driver.get(CPANEL_URL)

    # Isi kredensial
    log.info("Login ke cPanel…")
    wait.until(EC.presence_of_element_located((By.ID, "user"))).send_keys(CPANEL_USER)
    driver.find_element(By.ID, "pass").send_keys(CPANEL_PASS)
    driver.find_element(By.ID, "login_submit").click()

    # Tunggu sampai URL mengandung /cpsess\d+/
    def token_ready(drv):
        return re.search(r"/cpsess\d+/", drv.current_url)

    try:
        wait.until(token_ready)
    except TimeoutException:
        driver.save_screenshot(os.path.join(LOG_DIR, "login_timeout.png"))
        log.exception("Login timeout atau tidak redirect ke URL bertoken.")
        raise

    m = re.search(r"^(https?://[^/]+/cpsess\d+/)", driver.current_url)
    if not m:
        driver.save_screenshot(os.path.join(LOG_DIR, "no_token_after_login.png"))
        log.error("Tidak menemukan token cpsess di URL setelah login: %s", driver.current_url)
        raise RuntimeError("Tidak menemukan token cpsess di URL setelah login.")
    token_base = m.group(1)
    log.info(f"Token OK: {token_base}")
    return token_base

# ========= NAVIGASI =========
def go_email_accounts_list(driver, wait, token_base: str):
    """Langsung ke list Email Accounts (lebih stabil)."""
    url = token_base + "frontend/jupiter/email_accounts/index.html#/list"
    log.info("Buka Email Accounts list: %s", url)
    driver.get(url)
    _wait_angular_ready(driver, 30)
    # indikator list siap: tabel atau tombol Create
    with try_all_frames(driver):
        try:
            wait.until(EC.presence_of_element_located((By.ID, "accounts_table")))
        except TimeoutException:
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#btnCreateEmailAccount")))
    driver.save_screenshot(os.path.join(LOG_DIR, "01_email_list.png"))

def go_to_create_form(driver, wait, token_base: str):
    """Langsung ke route create, lalu tunggu field unik form."""
    url = token_base + "frontend/jupiter/email_accounts/index.html#/create/"
    log.info("Buka Create via hash: %s", url)
    driver.get(url)
    _wait_angular_ready(driver, 30)

    # Tunggu loading panel hilang jika ada
    try:
        panel = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "createLoadingPanel")))
        WebDriverWait(driver, 20).until(EC.invisibility_of_element(panel))
    except TimeoutException:
        pass

    # Field unik form: username
    with try_all_frames(driver):
        el = WebDriverWait(driver, 25).until(
            EC.visibility_of_element_located((By.ID, "txtUserName"))
        )
    log.info("Form Create terdeteksi.")
    driver.save_screenshot(os.path.join(LOG_DIR, "02_create_form.png"))
    return el

def _find_password_input(driver, wait):
    # cari input password yg terlihat di dalam <password>
    cands = driver.find_elements(By.CSS_SELECTOR, "password input[type='password']")
    for e in cands:
        try:
            if e.is_displayed():
                return e
        except Exception:
            pass
    # fallback aman
    return wait.until(EC.visibility_of_element_located(
        (By.CSS_SELECTOR, "input[type='password']:not([style*='display:none'])")
    ))

def _get_selected_domain_text(driver) -> str:
    """Ambil teks domain yang tampil di sisi kanan username (span.domain-text)."""
    try:
        span = driver.find_element(By.CSS_SELECTOR, "#spanAddEmailAccountDomains .domain-text")
        return (_text_of(span).lstrip("@") or "").strip()
    except Exception:
        return ""

# ========= FORM ISIAN (KHUSUS UI Jupiter) =========
def fill_create_form(driver, wait, localpart: str, pwd: str,
                     prefer_unlimited=True, send_welcome=True, stay_after_create=True):
    log.info("Isi form: user=%s", localpart)
    with try_all_frames(driver):
        # Username
        username_input = wait.until(EC.element_to_be_clickable((By.ID, "txtUserName")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", username_input)
        try:
            username_input.clear()
        except Exception:
            pass
        _js_set_value(driver, username_input, localpart)

        # Domain: hanya kalau ada dropdown DAN env DOMAIN diisi
        if DOMAIN:
            domains_len = driver.execute_script("return (window.PAGE && PAGE.mailDomains && PAGE.mailDomains.length) || 0;")
            if domains_len > 1:
                try:
                    ddl = driver.find_element(By.ID, "ddlDomain")
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", ddl)
                    ddl.click()
                    opt = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, f"//select[@id='ddlDomain']/option[normalize-space(text())='{DOMAIN}']"))
                    )
                    opt.click()
                    log.info("Pilih domain: %s", DOMAIN)
                except Exception as e:
                    log.warning("Dropdown domain tidak dapat dipilih (%s). Lanjut default.", e)
            else:
                log.info("Hanya 1 domain aktif di cPanel (dropdown tidak dirender).")

        # Password
        pwd_input = _find_password_input(driver, wait)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pwd_input)
        try:
            pwd_input.clear()
        except Exception:
            pass
        _js_set_value(driver, pwd_input, pwd)

        # Optional Settings (toggle panel jika perlu)
        try:
            btn_opt = driver.find_element(By.ID, "btnShowOptionalSettings")
            if btn_opt.is_displayed():
                opened = driver.execute_script("return !!document.querySelector('#optionalSettingsDiv');")
                if not opened:
                    try:
                        btn_opt.click()
                    except ElementClickInterceptedException:
                        driver.execute_script("arguments[0].click();", btn_opt)
        except Exception:
            pass

        # Quota: Unlimited
        if prefer_unlimited:
            try:
                unlim = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "unlimitedQuota"))
                )
                if not unlim.is_selected():
                    driver.execute_script("arguments[0].click();", unlim)
                log.info("Quota: Unlimited")
            except Exception as e:
                log.warning("Set Unlimited quota gagal (%s).", e)

        # Welcome email
        try:
            cb = driver.find_element(By.ID, "send_welcome_email")
            if cb.is_displayed() and cb.is_enabled():
                if send_welcome != cb.is_selected():
                    driver.execute_script("arguments[0].click();", cb)
        except Exception:
            pass

        # Stay on page
        try:
            stay = driver.find_element(By.ID, "stay")
            if stay_after_create != stay.is_selected():
                driver.execute_script("arguments[0].click();", stay)
            log.info("Stay after Create: %s", "ON" if stay_after_create else "OFF")
        except Exception:
            log.warning("Checkbox 'stay' tidak ditemukan (abaikan).")

        # Trigger blur/validator Angular (biar meter settle)
        try:
            username_input.send_keys(Keys.TAB)
            pwd_input.send_keys(Keys.TAB)
        except Exception:
            pass

        # Domain final (untuk log/cek)
        final_domain = DOMAIN or _get_selected_domain_text(driver)
        return final_domain

# ========= SUBMIT & VERIFIKASI =========
def submit_create(driver, wait):
    # 1) Coba submit via ENTER di password (kadang hook submit listen di sana)
    try:
        pwd_input = _find_password_input(driver, wait)
        pwd_input.send_keys(Keys.ENTER)
        log.info("Coba submit via ENTER.")
        time.sleep(0.3)  # beri kesempatan hook submit jalan
    except Exception:
        pass

    # 2) Tunggu tombol 'cukup siap'; jika gagal, lanjut paksa klik + log diag
    try:
        wait_create_button_ready(driver, timeout=30)
    except TimeoutException:
        _dump_create_button_diagnostics(driver, tag="pre-force-click")

    # 3) Klik tombol (native → fallback JS)
    with try_all_frames(driver):
        btn = wait.until(EC.presence_of_element_located((By.ID, "btnCreateEmailAccount")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        try:
            WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "btnCreateEmailAccount")))
            btn.click()
            log.info("Klik Create (native).")
        except Exception as e:
            log.warning("Klik native gagal (%s). Pakai JS.", e)
            driver.execute_script("arguments[0].click();", btn)
            log.info("Klik Create (JS forced).")

def wait_create_cycle(driver, timeout=30):
    """
    Dipakai ketika 'Stay on this page' aktif:
    - Tunggu loading panel (#createLoadingPanel) muncul lalu hilang
    - Tunggu username field kosong kembali (form reset)
    """
    try:
        WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.ID, "createLoadingPanel")))
    except TimeoutException:
        pass

    try:
        panel = driver.find_element(By.ID, "createLoadingPanel")
        WebDriverWait(driver, timeout).until(EC.invisibility_of_element(panel))
    except Exception:
        pass

    # Form reset? (username kosong)
    try:
        username_input = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "txtUserName")))
        val = username_input.get_attribute("value") or ""
        if val.strip() == "":
            return True
    except TimeoutException:
        pass

    # Alternatif: cek alert sukses
    try:
        ok = driver.execute_script("""
            const al = document.querySelector('cp-alert-list');
            return al && al.innerText && /created/i.test(al.innerText);
        """)
        if ok:
            return True
    except Exception:
        pass

    driver.save_screenshot(os.path.join(LOG_DIR, "after_create_unclear.png"))
    return False

def wait_after_submit(driver, wait):
    """
    Jika tidak pakai 'stay', ini menunggu redirect ke #/list atau tabel muncul.
    Untuk flow dengan 'stay', fungsi ini tetap aman (cepat keluar).
    """
    try:
        WebDriverWait(driver, 10).until(
            lambda d: (d.execute_script("return location.hash || ''") or "").startswith("#/list")
        )
    except TimeoutException:
        # alternatif: tunggu tabel muncul
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "accounts_table")))
        except TimeoutException:
            driver.save_screenshot(os.path.join(LOG_DIR, "after_submit_unknown.png"))
            log.warning("Tidak redirect ke list & tabel tidak muncul (UNKNOWN).")
            return False
    return True

def assert_account_exists(driver, wait, email_addr: str) -> bool:
    try:
        wait.until(EC.presence_of_element_located((By.ID, "accounts_table")))
        xpath = f"//tbody[@id='accounts_table_body']//td[contains(@class,'name-column')]//span[contains(@class,'account-name')][normalize-space(text())='{email_addr}']"
        WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.XPATH, xpath)))
        log.info("Terverifikasi muncul di list: %s", email_addr)
        return True
    except TimeoutException:
        driver.save_screenshot(os.path.join(LOG_DIR, f"verify_missing_{email_addr.replace('@','_')}.png"))
        log.warning("Tidak menemukan baris untuk: %s", email_addr)
        return False

# ========= MAIN (BATCH) =========
def main():
    if not all([CPANEL_URL, CPANEL_USER, CPANEL_PASS]):
        log.error("Env CPANEL_URL/CPANEL_USER/CPANEL_PASS wajib diisi.")
        print("Env CPANEL_URL/CPANEL_USER/CPANEL_PASS wajib diisi.", file=sys.stderr)
        sys.exit(2)

    opts = webdriver.ChromeOptions()
    # opts.add_argument("--headless=new")  # aktifkan untuk CI/headless

    log.info("Menghubungkan ke Selenium: http://s-chromium:4444")
    driver = webdriver.Remote("http://s-chromium:4444", options=opts)
    wait = waitx(driver, 25)

    try:
        # 1) Login & ambil token base
        token_base = login_and_get_token_base(driver, wait)

        successes = dupes = unknowns = 0

        # 2) Loop pembuatan akun
        for i in range(1, COUNT + 1):
            local = f"{EMAIL_PREFIX}{i:03d}"  # akun001, akun002, ...
            pwd   = PASSWORD_STATIC or gen_pass()
            log.info(f"[{i}/{COUNT}] Proses {local}@{DOMAIN or '(default)'}")

            # Pastikan mulai dari form create (langsung ke route)
            try:
                go_to_create_form(driver, wait, token_base)
            except Exception as e:
                log.warning("Gagal membuka form Create, refresh & coba lagi… (%s)", e)
                driver.refresh()
                go_email_accounts_list(driver, wait, token_base)
                go_to_create_form(driver, wait, token_base)

            # Isi form
            final_domain = fill_create_form(
                driver, wait, local, pwd,
                prefer_unlimited=True,
                send_welcome=True,
                stay_after_create=True
            )

            # Delay mikro agar meter/validator settle
            time.sleep(0.3)

            # Submit
            submit_create(driver, wait)

            # Tunggu siklus create selesai tanpa redirect
            if not wait_create_cycle(driver, timeout=35):
                log.warning("Create tidak terkonfirmasi; coba sekali lagi.")
                # satu retry aman
                try:
                    submit_create(driver, wait)
                    if not wait_create_cycle(driver, timeout=35):
                        unknowns += 1
                        continue
                except Exception:
                    unknowns += 1
                    continue

            # (Jika tidak stay) tunggu pasca-submit; kalau stay, ini cepat selesai
            if not wait_after_submit(driver, wait):
                unknowns += 1
                continue

            # Konfirmasi apakah akun tampil di list
            email_full = f"{local}@{final_domain}" if final_domain else local
            if assert_account_exists(driver, wait, email_full):
                successes += 1
            else:
                # coba deteksi duplikat
                dup_xp = "//*[contains(., 'already exists') or contains(., 'sudah ada') or contains(., 'duplicate')]"
                with try_all_frames(driver):
                    if driver.find_elements(By.XPATH, dup_xp):
                        dupes += 1
                    else:
                        unknowns += 1

        log.info("SUMMARY: OK=%s, DUPLICATE=%s, UNKNOWN=%s", successes, dupes, unknowns)
        print(f"\nSUMMARY: OK={successes}, DUPLICATE={dupes}, UNKNOWN={unknowns}")

    except Exception:
        log.exception("Fatal error saat eksekusi.")
        raise
    finally:
        log.info("Menutup sesi browser.")
        driver.quit()

if __name__ == "__main__":
    main()

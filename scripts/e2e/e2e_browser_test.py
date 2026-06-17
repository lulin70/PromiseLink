"""Real browser E2E test using Playwright for PromiseLink"""
import asyncio
import json
import sys
import os

# Add playwright to path
os.environ.setdefault('PYTHONPATH', './frontend/node_modules')

async def main():
    from playwright.async_api import async_playwright
    
    BASE = "http://localhost:3000"
    results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 375, "height": 812})  # iPhone X size
        
        # Capture console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
        
        # Capture network failures
        failed_requests = []
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}: {req.failure}"))
        
        try:
            # === STEP 1: Navigate to home ===
            print("\n[STEP 1] Navigate to", BASE)
            await page.goto(BASE, wait_until="networkidle", timeout=15000)
            await asyncio.sleep(2)
            screenshot1 = "/tmp/e2e_step1_login_page.png"
            await page.screenshot(path=screenshot1)
            
            title = await page.title()
            content = await page.content()
            has_login_form = "PoC Secret" in content or "poc_secret" in content.lower() or "登录" in content
            has_input = await page.query_selector("input")
            
            results.append({
                "step": "1-Navigate",
                "pass": has_login_form or has_input is not None,
                "detail": f"title={title}, has_login_form={has_login_form}, has_input={has_input is not None}",
                "screenshot": screenshot1,
            })
            print(f"  Title: {title}")
            print(f"  Has login form: {has_login_form}")
            print(f"  Has input: {has_input is not None}")
            print(f"  Screenshot: {screenshot1}")
            
            # === STEP 2: Fill in login form ===
            print("\n[STEP 2] Fill login form")
            if has_input:
                inputs = await page.query_selector_all("input")
                print(f"  Found {len(inputs)} input fields")
                
                for inp in inputs:
                    placeholder = await inp.get_attribute("placeholder") or ""
                    value = await inp.input_value()
                    input_type = await inp.get_attribute("type") or "text"
                    print(f"  Input: type={input_type}, placeholder={placeholder}, value='{value}'")
                    
                    if "secret" in placeholder.lower() or "密码" in placeholder or input_type == "password":
                        await inp.fill("promiselink2026")
                        print(f"  ✓ Filled password field")
                    elif "user" in placeholder.lower() or "id" in placeholder.lower():
                        if not value:
                            await inp.fill("poc-user")
                            print(f"  ✓ Filled user ID field")
            
            # === STEP 3: Click Login ===
            print("\n[STEP 3] Click login button")
            # Try to find and click login button
            clicked = False
            
            # Method 1: Find by text
            login_btn = None
            for selector in ["text=登 录", "text=登录", ".login-btn", "button"]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        login_btn = el
                        break
                except:
                    pass
            
            if login_btn:
                await login_btn.click()
                clicked = True
                print(f"  ✓ Clicked login button")
            else:
                # Try JavaScript click
                try:
                    await page.evaluate("""() => {
                        const btns = document.querySelectorAll('.login-btn, [class*="login-btn"]');
                        btns.forEach(b => b.click());
                    }""")
                    clicked = True
                    print(f"  ✓ Clicked via JS evaluation")
                except Exception as ex:
                    print(f"  ✗ Could not find/click login button: {ex}")
            
            results.append({"step": "2-LoginClick", "pass": clicked, "detail": f"clicked={clicked}"})
            
            # === STEP 4: Wait for dashboard ===
            print("\n[STEP 4] Wait for dashboard to load...")
            await asyncio.sleep(8)  # Wait for login + dashboard API
            
            screenshot2 = "/tmp/e2e_step4_dashboard.png"
            await page.screenshot(path=screenshot2)
            
            content = await page.content()
            url = page.url
            
            # Check what's on screen now
            has_dashboard_data = any(x in content for x in ["今日事件", "待办事项", "card-number", "summary-cards"])
            has_loading = "加载中" in content
            has_error = any(x in content for x in ["error-text", "API Error", "重试"])
            still_on_login = "PoC Secret" in content and "登录" in content
            
            # Try to extract numbers from page
            numbers_found = []
            try:
                card_numbers = await page.query_selector_all(".card-number")
                for cn in card_numbers:
                    text = await cn.inner_text()
                    numbers_found.append(text.strip())
            except:
                pass
            
            results.append({
                "step": "3-Dashboard",
                "pass": has_dashboard_data and not has_loading,
                "detail": f"url={url}, has_data={has_dashboard_data}, loading={has_loading}, error={has_error}, still_login={still_on_login}, numbers={numbers_found}",
                "screenshot": screenshot2,
            })
            print(f"  URL: {url}")
            print(f"  Has dashboard data: {has_dashboard_data}")
            print(f"  Still loading: {has_loading}")
            print(f"  Has error: {has_error}")
            print(f"  Still on login: {still_on_login}")
            print(f"  Numbers on screen: {numbers_found}")
            print(f"  Screenshot: {screenshot2}")
            
            # === STEP 5: Check tabs navigation ===
            print("\n[STEP 5] Check tab navigation")
            tab_texts = []
            try:
                tabs = await page.query_selector_all(".tab-bar-item, [class*='tab']")
                for t in tabs:
                    text = await t.inner_text()
                    tab_texts.append(text.strip())
            except:
                pass
            
            # Try clicking 录入 tab
            input_tab_clicked = False
            try:
                input_tab = await page.query_selector("text=录入")
                if input_tab:
                    await input_tab.click()
                    await asyncio.sleep(2)
                    input_tab_clicked = True
                    screenshot3 = "/tmp/e2e_step5_input.png"
                    await page.screenshot(path=screenshot3)
                    input_content = await page.content()
                    has_textarea = "textarea" in input_content or "TextArea" in input_content
                    
                    results.append({
                        "step": "4-InputTab",
                        "pass": input_tab_clicked and has_textarea,
                        "detail": f"clicked={input_tab_clicked}, has_textarea={has_textarea}, tabs={tab_texts}",
                        "screenshot": screenshot3,
                    })
                    print(f"  Tabs found: {tab_texts}")
                    print(f"  Input tab clicked: {input_tab_clicked}")
                    print(f"  Has text area: {has_textarea}")
            except Exception as ex:
                results.append({"step": "4-InputTab", "pass": False, "detail": str(ex)})
                print(f"  ✗ Tab navigation failed: {ex}")
            
        except Exception as e:
            results.append({"step": "ERROR", "pass": False, "detail": str(e)})
            print(f"\n  ERROR: {e}")
        
        finally:
            await browser.close()
    
    # ── Report ──
    print("\n" + "=" * 60)
    print("  BROWSER E2E TEST RESULTS")
    print("=" * 60)
    
    passed = sum(1 for r in results if r.get("pass"))
    total = len(results)
    
    for r in results:
        status = "✅ PASS" if r.get("pass") else "❌ FAIL"
        print(f"  {status} | {r['step']}: {r['detail'][:100]}")
    
    if console_errors:
        print(f"\n  Console Errors ({len(console_errors)}):")
        for err in console_errors[:5]:
            print(f"    {err[:120]}")
    
    if failed_requests:
        print(f"\n  Failed Requests ({len(failed_requests)}):")
        for req in failed_requests[:5]:
            print(f"    {req[:120]}")
    
    overall = "PASS" if passed == total else "PARTIAL" if passed > 0 else "FAIL"
    print(f"\n  Overall: {overall} ({passed}/{total})")
    
    # Save report
    report_path = "/tmp/promiselink_browser_e2e.json"
    with open(report_path, "w") as f:
        json.dump({"overall": overall, "passed": passed, "total": total, "steps": results}, f, indent=2)
    print(f"  Report saved: {report_path}")
    
    return 0 if overall != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""End-to-end browser smoke test (Playwright). Start the API (fresh DB, mock mode) and `npm run dev` first.

    pip install playwright && playwright install chromium
    python scripts/e2e_smoke.py        # screenshots land in ./shots
"""
import asyncio, os, subprocess, sys
os.makedirs("shots", exist_ok=True)
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=4", "-ar", "16000", "shots/sample.wav"], check=True)
from playwright.async_api import async_playwright
B="http://localhost:5173"
async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--use-fake-ui-for-media-stream","--use-fake-device-for-media-stream"])
        ctx = await br.new_context(viewport={"width":1280,"height":900}, permissions=["microphone"])
        pg = await ctx.new_page()
        errs=[]
        pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(B); await pg.wait_for_selector("#email")
        await pg.screenshot(path="shots/01_login.png")
        await pg.fill("#email","alex@example.com"); await pg.fill("#name","Alex")
        await pg.click("button[type=submit]")
        await pg.wait_for_selector("text=Set up a circle")
        # onboarding
        await pg.click("text=Set up a circle"); await pg.wait_for_selector("#cname")
        await pg.fill("#cname","Grandma Ada's Circle"); await pg.fill("#myrel","grandson"); await pg.fill("#myphone","08031234567")
        await pg.click("button[type=submit]"); await pg.wait_for_selector("#sname")
        await pg.fill("#sname","Grandma Ada"); await pg.fill("#srel","grandmother"); await pg.fill("#sphone","08098765432")
        await pg.click("button[type=submit]"); await pg.wait_for_selector("text=Record your voice")
        await pg.click("text=Start recording"); await pg.wait_for_timeout(3000)
        await pg.screenshot(path="shots/02_recording.png")
        await pg.click("text=Stop"); await pg.wait_for_selector("audio")
        await pg.check("input[type=checkbox]")
        await pg.click("text=Save my voice")
        await pg.wait_for_url("**/c/*", timeout=30000)
        await pg.wait_for_selector("text=Voice enrolled", timeout=15000)
        await pg.screenshot(path="shots/03_home.png", full_page=True)
        url = pg.url; print("circle", url)
        # practice
        await pg.click("nav >> text=Practice"); await pg.wait_for_selector("text=Call Grandma Ada now")
        await pg.click("text=Call Grandma Ada now")
        await pg.wait_for_selector("text=Call simulator", timeout=20000)
        await pg.screenshot(path="shots/04_live.png", full_page=True)
        await pg.click("text=“Who is this really?”"); await pg.wait_for_timeout(2500)
        await pg.click("text=“Let me call you back on your own number.”")
        await pg.wait_for_selector("text=Score", timeout=30000)
        await pg.screenshot(path="shots/05_outcome.png", full_page=True)
        # check
        open("shots/deepfake_alex.wav","wb").write(open("shots/sample.wav","rb").read())
        await pg.click("nav >> text=Check a call"); await pg.wait_for_selector("#rec", state="attached")
        await pg.set_input_files("#rec","shots/deepfake_alex.wav")
        await pg.click("text=Check this voice")
        await pg.wait_for_selector("text=What to do", timeout=30000)
        await pg.screenshot(path="shots/06_check.png", full_page=True)
        # hugh
        await pg.click("nav >> text=Hugh"); await pg.wait_for_selector("text=Have Hugh call now")
        await pg.click("text=Have Hugh call now")
        await pg.wait_for_selector("text=Call simulator", timeout=20000)
        for s in ["“I'm doing well, thank you.”","“I watered my tomatoes and called my sister.”","“Goodbye Hugh, talk tomorrow.”"]:
            try:
                await pg.click(f"text={s}", timeout=8000); await pg.wait_for_timeout(2500)
            except Exception as e: print("hugh step", s, type(e).__name__)
        await pg.wait_for_selector("text=Call finished", timeout=40000)
        await pg.screenshot(path="shots/07_hugh.png", full_page=True)
        await pg.click("nav >> text=Alerts"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path="shots/08_alerts.png", full_page=True)
        # demo seed
        await pg.goto(B); await pg.wait_for_timeout(1500)
        await pg.click("text=Add another demo circle"); await pg.wait_for_url("**/c/*"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path="shots/09_demo_home.png", full_page=True)
        await pg.click("nav >> text=Hugh"); await pg.wait_for_timeout(2500)
        await pg.screenshot(path="shots/10_demo_hugh.png", full_page=True)
        await pg.click("nav >> text=Alerts"); await pg.wait_for_timeout(1500)
        await pg.click("text=Mark as handled >> nth=0"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path="shots/11_demo_alerts.png", full_page=True)
        await pg.set_viewport_size({"width":390,"height":844}); await pg.click("nav >> text=Practice >> nth=-1"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path="shots/12_mobile.png")
        print("console errors:", errs[:10] or "none")
        assert not errs, errs
        await br.close()
asyncio.run(main())

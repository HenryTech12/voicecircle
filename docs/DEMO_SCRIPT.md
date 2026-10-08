# VoiceCircle: 3-minute demo script

**Setup:** run the API and web app (see README). Sign in as `alex@example.com`. Keep a file named `deepfake_alex.wav` ready (any audio file works in mock mode). For a live demo, use a real Telnyx number and your own phone as the senior's number.

| Time | Screen | Say / do |
| --- | --- | --- |
| 0:00–0:20 | Login | "Voice-clone scams now copy a grandchild's voice from a 10-second clip. VoiceCircle turns the family's real voices into the defence." |
| 0:20–0:45 | Onboarding: record voice | Create "Grandma Ada's Circle", add Ada's phone, record Alex's voice. Point out the consent statement. "Nothing is cloned without consent." |
| 0:45–1:30 | Practice | Pick Alex's voice, "Grandchild in trouble", **Hard**, then **Call Grandma Ada now**. The opener in Alex's cloned voice appears. Answer "Who is this really?", then "Let me call you back on your own number." The call wraps up with the disclosure and shows **Score 90, Checked who was calling** plus coaching tips. |
| 1:30–2:00 | Check a call | Upload `deepfake_alex.wav` and claim it's Alex. The big red **Looks FAKE** appears with "What to do" advice. Mention that clones from our own practice calls are always detected too. |
| 2:00–2:40 | Hugh (demo data) | Go home and **Add another demo circle**, then open Hugh. "Two weeks of daily chats. Last Monday Ada's pace dropped and her pauses doubled." Point at the baseline line and the flags. "It's a nudge to check in, not a diagnosis." |
| 2:40–3:00 | Alerts | Show the three alerts: a recording that looked fake (urgent), a practice call where Ada nearly went along with it, and Hugh's wellbeing change. Trusted contacts also get these by SMS. Mark one as handled. Close: "No app for Grandma. Just the voices she trusts." |

**Backup:** if a live call fails, switch `MOCK_PROVIDERS=true`. The simulator runs the same call engine.

# Preserved Media Downloader baselines

Regression baselines used for the merged RNGN Media desktop app. The original ZIP bytes are preserved in the migration workspace/user archive; the first normal Git commit records their exact hashes instead of adding binaries to source history.

- `Media_Downloader_Premiere_Windows_v5_16_Installer_Resilience_FIX.zip`  
  SHA-256: `cfc8c59e2faca752cc060a47d4c0512c88349e69991bcc216a9013b8140a8d35`
- `Media_Downloader_Premiere_Windows_v5_16_1_YOUTUBE_ANALYSIS_FIX.zip`  
  SHA-256: `780c11f338494dab36456d845847137df92ecaee38b4711f1e7592a4b7e52021`

v5.16 была последней подтверждённо рабочей сборкой пользователя. v5.16.1 — минимальный YouTube analysis fix поверх этой базы. Не использовать ветку 6.x как основу для регрессий.

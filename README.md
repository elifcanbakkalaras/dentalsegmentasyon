# Okuyucu çalışması sunucusu

Panoramik radyograflarda model bulgularının hekimler tarafından puanlandığı
küçük web sunucusu. Yalnızca Python 3.8+ standart kütüphanesini kullanır.

| Dosya | Görev |
|---|---|
| `reader_server.py` | HTTP(S) sunucusu, kullanıcı yönetimi (tuzlu parola özetleri), puanların kaydı |
| `rating.html` | Okuyucu arayüzü |
| `admin.html` | Yönetici arayüzü (ilerleme, okuyucular arası ayrışma) |
| `KURULUM.txt` | VPS kurulum adımları (HTTPS, systemd) |

Görüntüler (`images640/`), kullanıcılar (`users.json`) ve puanlar (`data/`)
bu depoda **yoktur** ve `.gitignore` ile dışarıda tutulur; sunucuya ayrıca
kopyalanır.

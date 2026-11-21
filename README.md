# Okuyucu çalışması sunucusu

Panoramik radyograflarda model bulgularının hekimler tarafından puanlandığı
küçük web sunucusu. Yalnızca Python 3.8+ standart kütüphanesini kullanır.

| Dosya | Görev |
|---|---|
| `reader_server.py` | HTTP(S) sunucusu, kullanıcı yönetimi (tuzlu parola özetleri), puanların kaydı |
| `rating.html` | Okuyucu arayüzü |
| `admin.html` | Yönetici arayüzü (ilerleme, okuyucular arası ayrışma) |

Görüntüler (`images640/`, 150 PNG), kullanıcılar (`users.json`) ve puanlar (`data/`)
bu depoda **yoktur** ve `.gitignore` ile dışarıda tutulur. Görüntüler sunucuya ayrıca
kopyalanır. `manifest`, `findings.json` ve model tahminleri hiçbir zaman sunucuya
gitmez. Depo herkese açıktır: içine hasta verisi, şifre ya da bulgu–model eşlemesi koymayın.

## Kurulum (VPS, Linux)

### 1. Kodu ve görüntüleri sunucuya alın

Sunucuda:

```bash
sudo apt install git python3
sudo mkdir -p /opt/okuyucu && sudo chown $USER /opt/okuyucu
git clone https://github.com/elifcanbakkalaras/dentalsegmentasyon.git /opt/okuyucu
```

Kendi bilgisayarınızda, bu klasörün içindeyken (görüntüler GitHub'a gitmez):

```bash
scp -r images640 kullanici@SUNUCU:/opt/okuyucu/
```

Sunucuda kontrol: `ls /opt/okuyucu/images640 | wc -l` → `150`

### 2. Servis kullanıcısı ve hesaplar

```bash
sudo useradd --system --home-dir /opt/okuyucu --shell /usr/sbin/nologin okuyucu
sudo chown -R okuyucu: /opt/okuyucu
cd /opt/okuyucu
sudo -u okuyucu python3 reader_server.py --add-user O1
sudo -u okuyucu python3 reader_server.py --add-user O2
sudo -u okuyucu python3 reader_server.py --add-user admin --admin
sudo timedatectl set-timezone Europe/Istanbul   # kayıt saatleri sunucu saatiyle yazılır
```

Her `--add-user` bir şifre yazdırır; not edin. Şifreyi unutursanız aynı komutla yeniden
oluşturun (eskisi geçersiz olur; sunucuyu yeniden başlatmak gerekmez).
Sunucuyu her zaman `okuyucu` kullanıcısıyla çalıştırın: root ile elle çalıştırırsanız
`data/` root'a ait olur ve servis kaydedemez.

### 3. HTTPS (şart: şifreler her istekte gider)

**A) Alan adı + Caddy (önerilen).** Caddy sertifikayı kendisi alır. Alan adının DNS A
kaydı sunucunun IP'sini göstermeli; 80 ve 443 portları açık olmalı
(`sudo ufw allow 80,443/tcp`). 8080'i dışarı açmayın.

```bash
sudo apt install caddy   # bulunamazsa: https://caddyserver.com/docs/install
```

`/etc/caddy/Caddyfile` (içindeki örneğin yerine):

```
okuyucu.ALANADINIZ.com {
    reverse_proxy 127.0.0.1:8080
}
```

```bash
sudo systemctl reload caddy
```

Adres: `https://okuyucu.ALANADINIZ.com`

**B) Elinizde sertifika varsa, Caddy'siz.** 4. adımdaki `ExecStart` satırını aşağıdakiyle
değiştirin, 8443'ü güvenlik duvarında açın; anahtar dosyası `okuyucu` kullanıcısınca
okunabilir olmalı. Adres: `https://SUNUCU:8443`

```
ExecStart=/usr/bin/python3 /opt/okuyucu/reader_server.py --port 8443 --cert /yol/fullchain.pem --key /yol/privkey.pem
```

### 4. Sürekli çalıştırma (systemd)

`/etc/systemd/system/okuyucu.service`:

```ini
[Unit]
Description=Okuyucu calismasi
After=network.target

[Service]
User=okuyucu
WorkingDirectory=/opt/okuyucu
ExecStart=/usr/bin/python3 /opt/okuyucu/reader_server.py --host 127.0.0.1 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now okuyucu
journalctl -u okuyucu -f   # kayıtları izlemek
```

### 5. Hekimlere vermeden önce deneyin, sonra deneme kayıtlarını silin

`https://ADRES/` → O1 ile girip birkaç işaret yapın; `/admin`'de göründüğüne bakın.
Deneme sekmelerini kapatın, sonra:

```bash
sudo systemctl stop okuyucu
sudo rm -rf /opt/okuyucu/data
sudo systemctl start okuyucu
```

Silmezseniz deneme işaretleri O1'in sonuçlarına karışır. (admin ile `/` sayfasında işaret
yaparsanız `admin` de sonuçlarda bir okuyucu gibi görünür.)

### Kod güncellemesi

GitHub'a yeni sürüm gönderdikten sonra sunucuda:

```bash
cd /opt/okuyucu && sudo -u okuyucu git pull && sudo systemctl restart okuyucu
```

`users.json`, `data/` ve `images640/` git dışında olduğu için güncellemeden etkilenmez.

## Kullanım

- **Hekim:** `https://ADRES/` → kullanıcı adı O1 (veya O2) ve şifresi. Her işaret birkaç
  saniye içinde sunucuya kaydedilir ("Sunucuya kaydedildi" yazar). Kalem/parmak/fare ile
  çalışır; iPad'de Safari'den açın. Aynı anda tek cihazda çalışın: iki cihazda açıksa son
  kaydeden diğerinin üzerine yazar. Cihaz değiştirirken eskisinde sayfayı kapatın,
  yenisinde sayfayı yenileyin.
- **Siz:** `https://ADRES/admin` → admin ve şifresi. İlerleme, yanıtlar ve çizilen kutular;
  "Yalnız okuyucuların ayrıştığı hastalar" filtresi; "Tümünü indir (JSON)".

## Kayıtlar

- `data/rating_O1.json`, `data/rating_O2.json`: güncel hali
- `data/history/`: her 10 dakikada bir kopya; yanlışlıkla silinen iş geri alınabilir
- Çalışma bitince `/admin`'den "Tümünü indir" ile alın, sonra sunucudaki klasörü
  (görüntüler dahil) silin.

## Güvenlik

- Sayfa arama motorlarına kapalıdır; yine de adresi yalnız iki hekimle paylaşın.
- 10 hatalı girişte o IP 10 dakika engellenir (Caddy arkasında gerçek istemci IP'si
  `X-Forwarded-For` başlığından alınır; diğer kullanıcılar etkilenmez).
- Okuyucular `/admin` sayfasını ve birbirlerinin sonuçlarını göremez.
- Sunucuda hangi bulgunun hangi modelden geldiği bilgisi yoktur (çalışma kör kalır).

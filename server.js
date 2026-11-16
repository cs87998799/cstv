/* Sarah TV — Push Server (ঐচ্ছিক টেমপ্লেট)
 * কাজ: নামাজের ওয়াক্তে সব সাবস্ক্রাইবারকে পুশ নোটিফিকেশন পাঠায় (সাইট/অ্যাপ বন্ধ থাকলেও)।
 * চালানো: README.md দেখুন।  (এই কোড আপনার সার্ভারে চালাতে হবে — আমি এখানে টেস্ট করতে পারিনি)
 */
const express = require('express');
const cors = require('cors');
const webpush = require('web-push');
const fs = require('fs');

const PUB = process.env.VAPID_PUBLIC, PRIV = process.env.VAPID_PRIVATE;
const CONTACT = process.env.CONTACT || 'admin@example.com';
const ADMIN_KEY = process.env.ADMIN_KEY || '';            // /broadcast এর পাসওয়ার্ড
const PORT = process.env.PORT || 3000;
if (!PUB || !PRIV) { console.error('VAPID_PUBLIC / VAPID_PRIVATE সেট করুন'); process.exit(1); }
webpush.setVapidDetails('mailto:' + CONTACT, PUB, PRIV);

/* ---- ঢাকার নামাজের সময় (ওয়েবসাইটের হিসাবের হুবহু কপি) ---- */
const LAT0 = 23.8103, LON0 = 90.4125, TZ = 6;
const FAJR_ADD = 2, ZUHR_OFFSET = 3.5, MAGHRIB_ADD = 3.5, ISHA_ADD = 1, SEHRI_BEFORE_FAJR = 1, ASR_SHADOW = 2;
const rad = x => x * Math.PI / 180, deg = x => x * 180 / Math.PI;
function sunTimes(y, m, d, lat, lon) {
    var LAT = (lat == null ? LAT0 : lat), LON = (lon == null ? LON0 : lon);
    var jd = Date.UTC(y, m - 1, d, 6, 0, 0) / 864e5 + 2440587.5;     // স্থানীয় দুপুর ১২টা
    var T = (jd - 2451545) / 36525;
    var L0 = (280.46646 + T * (36000.76983 + T * 0.0003032)) % 360;
    var M = 357.52911 + T * (35999.05029 - 0.0001537 * T);
    var e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T);
    var C = Math.sin(rad(M)) * (1.914602 - T * (0.004817 + 0.000014 * T)) + Math.sin(rad(2 * M)) * (0.019993 - 0.000101 * T) + Math.sin(rad(3 * M)) * 0.000289;
    var om = 125.04 - 1934.136 * T;
    var lam = L0 + C - 0.00569 - 0.00478 * Math.sin(rad(om));
    var eps0 = 23 + (26 + ((21.448 - T * (46.815 + T * (0.00059 - T * 0.001813)))) / 60) / 60;
    var eps = eps0 + 0.00256 * Math.cos(rad(om));
    var decl = deg(Math.asin(Math.sin(rad(eps)) * Math.sin(rad(lam))));
    var y2 = Math.pow(Math.tan(rad(eps / 2)), 2);
    var eot = 4 * deg(y2 * Math.sin(2 * rad(L0)) - 2 * e * Math.sin(rad(M)) + 4 * e * y2 * Math.sin(rad(M)) * Math.cos(2 * rad(L0)) - 0.5 * y2 * y2 * Math.sin(4 * rad(L0)) - 1.25 * e * e * Math.sin(2 * rad(M)));
    var noon = 720 - 4 * LON - eot + TZ * 60;
    var H = function (alt) {
      var c = (Math.sin(rad(alt)) - Math.sin(rad(LAT)) * Math.sin(rad(decl))) / (Math.cos(rad(LAT)) * Math.cos(rad(decl)));
      return deg(Math.acos(Math.max(-1, Math.min(1, c)))) * 4;
    };
    var hs = H(-0.833);
    var asrAlt = deg(Math.atan(1 / (ASR_SHADOW + Math.tan(rad(Math.abs(LAT - decl))))));   // হানাফী আসর
    var r = Math.round;
    return {
      sunrise: r(noon - hs), sunset: r(noon + hs),
      fajr: r(noon - H(-18) + FAJR_ADD), sehri: r(noon - H(-18) + FAJR_ADD) - SEHRI_BEFORE_FAJR,
      zuhr: r(noon + ZUHR_OFFSET), asr: r(noon + H(asrAlt)),
      maghrib: r(noon + hs + MAGHRIB_ADD), isha: r(noon + H(-18) + ISHA_ADD)
    };
  }

/* ---- সাবস্ক্রিপশন সেভ ---- */
const FILE = process.env.SUBS_FILE || 'subs.json';
let subs = []; try { subs = JSON.parse(fs.readFileSync(FILE, 'utf8')); } catch (e) {}
const save = () => fs.writeFileSync(FILE, JSON.stringify(subs));

const app = express();
app.use(cors()); app.use(express.json({ limit: '50kb' }));
app.get('/health', (q, r) => r.json({ ok: true, subs: subs.length }));
app.post('/subscribe', (req, res) => {
  const { sub, prefs } = req.body || {};
  if (!sub || !sub.endpoint) return res.status(400).json({ ok: false });
  subs = subs.filter(s => s.sub.endpoint !== sub.endpoint); subs.push({ sub, prefs: prefs || {}, t: Date.now() }); save();
  res.json({ ok: true });
});
app.post('/unsubscribe', (req, res) => { subs = subs.filter(s => s.sub.endpoint !== (req.body || {}).endpoint); save(); res.json({ ok: true }); });
app.post('/broadcast', (req, res) => {                     // হাতে ঘোষণা পাঠাতে: {key,title,body,url}
  const b = req.body || {}; if (!ADMIN_KEY || b.key !== ADMIN_KEY) return res.status(403).json({ ok: false });
  sendAll({ title: b.title || 'Sarah TV', body: b.body || '', url: b.url || './', tag: 'broadcast' }); res.json({ ok: true, to: subs.length });
});

function sendAll(payload, filter) {
  const data = JSON.stringify(payload);
  subs.slice().forEach(s => {
    if (filter && !filter(s)) return;
    webpush.sendNotification(s.sub, data).catch(e => { if (e.statusCode === 404 || e.statusCode === 410) { subs = subs.filter(x => x !== s); save(); } });
  });
}

/* ---- প্রতি মিনিটে ওয়াক্ত চেক ---- */
const NAMES = { fajr: 'ফজর', zuhr: 'যোহর', asr: 'আসর', maghrib: 'মাগরিব', isha: 'এশা' };
let sentKey = '';
setInterval(() => {
  const d = new Date(Date.now() + TZ * 3600e3);
  const y = d.getUTCFullYear(), m = d.getUTCMonth() + 1, dd = d.getUTCDate(), min = d.getUTCHours() * 60 + d.getUTCMinutes();
  const st = sunTimes(y, m, dd);
  Object.keys(NAMES).forEach(k => {
    const key = y + '-' + m + '-' + dd + k;
    if (st[k] === min && sentKey.indexOf(key) < 0) {
      sentKey = (sentKey + '|' + key).slice(-400);
      sendAll({ title: '🕌 ' + NAMES[k] + ' নামাজের সময় হয়েছে', body: 'ঢাকার সময় অনুযায়ী', tag: 'namaz-' + k, url: './' }, s => s.prefs.prayer !== false);
    }
  });
}, 30000);

app.listen(PORT, () => console.log('Sarah push server on :' + PORT));

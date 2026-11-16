/* Sarah TV — OTP Server (কোনো npm প্যাকেজ লাগে না, Node 18+)
 * POST /otp/send   {phone:"+8801XXXXXXXXX"}            -> SMS এ কোড পাঠায়
 * POST /otp/verify {phone, code}                        -> {ok:true, token}
 * POST /otp/check  {phone, token}                       -> টোকেন ঠিক আছে কিনা (ভবিষ্যতে সার্ভার-সাইড চেকের জন্য)
 * GET  /health
 */
const http = require('http');
const crypto = require('crypto');

const PORT = +process.env.PORT || 3000;
const PROVIDER = (process.env.SMS_PROVIDER || 'console').toLowerCase();   // console | bulksmsbd | alphasms | twilio
const BRAND = process.env.BRAND || 'Sarah TV';
const OTP_LEN = Math.min(6, Math.max(4, +process.env.OTP_LENGTH || 6));
const TTL_MS = 5 * 60 * 1000, RESEND_MS = 60 * 1000, MAX_ATTEMPTS = 5;
const SECRET = process.env.OTP_SECRET || crypto.randomBytes(32).toString('hex');   // টোকেন সাইন করার গোপন কী (ঠিক রাখতে নিজে সেট করুন)
const ALLOWED = (process.env.ALLOWED_ORIGIN || '*').split(',').map(s => s.trim()).filter(Boolean);
if (ALLOWED.includes('*') && PROVIDER !== 'console') console.warn('⚠ ALLOWED_ORIGIN সেট করুন (যেমন https://yourname.github.io) — নইলে যে কেউ আপনার SMS ব্যবহার করতে পারে');

const store = new Map();   // phone -> {hash, exp, attempts, sentAt}
const hits = new Map();    // rate-limit: key -> [timestamps]
function rate(key, max, windowMs) {
  const now = Date.now(), arr = (hits.get(key) || []).filter(t => now - t < windowMs);
  if (arr.length >= max) { hits.set(key, arr); return false; }
  arr.push(now); hits.set(key, arr); return true;
}
setInterval(() => { const n = Date.now(); store.forEach((v, k) => { if (v.exp < n) store.delete(k); }); hits.forEach((v, k) => { if (!v.some(t => n - t < 3600e3)) hits.delete(k); }); }, 60000).unref();

const normPhone = p => { p = String(p || '').replace(/[\s-]/g, ''); return /^\+8801[3-9]\d{8}$/.test(p) ? p : null; };
const hashOf = (phone, code) => crypto.createHash('sha256').update(SECRET + '|' + phone + '|' + code).digest('hex');
const sign = s => crypto.createHmac('sha256', SECRET).update(s).digest('base64url');
const makeToken = phone => { const p = Buffer.from(JSON.stringify({ p: phone, e: Date.now() + 30 * 864e5 })).toString('base64url'); return p + '.' + sign(p); };
function checkToken(phone, token) {
  try { const [p, sg] = String(token).split('.'); if (!p || !sg) return false; const a = Buffer.from(sg), b = Buffer.from(sign(p)); if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return false; const d = JSON.parse(Buffer.from(p, 'base64url').toString()); return d.p === phone && d.e > Date.now(); } catch (e) { return false; }
}

/* ---------------- SMS providers ---------------- */
const smsText = code => `${BRAND} login code: ${code}. Valid for ${TTL_MS / 60000} minutes. Do not share this code.`;
const providers = {
  async console(phone, code) { console.log(`[OTP] ${phone} -> ${code}`); },
  async bulksmsbd(phone, code) {            // https://bulksmsbd.net  (API Key + Sender ID লাগবে)
    const q = new URLSearchParams({ api_key: process.env.BULKSMSBD_API_KEY, type: 'text', number: phone.slice(1), senderid: process.env.BULKSMSBD_SENDER_ID, message: smsText(code) });
    const r = await fetch('http://bulksmsbd.net/api/smsapi?' + q); const t = await r.text();
    let j = {}; try { j = JSON.parse(t); } catch (e) {}
    if (!(String(j.response_code) === '202' || /success/i.test(String(j.success_message || '')))) throw new Error('bulksmsbd: ' + t.slice(0, 200));
  },
  async alphasms(phone, code) {             // https://sms.net.bd  (API Key লাগবে)
    const r = await fetch('https://api.sms.net.bd/sendsms', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ api_key: process.env.ALPHASMS_API_KEY, msg: smsText(code), to: phone.slice(1) }) });
    const j = await r.json().catch(() => ({})); if (j.error !== 0) throw new Error('alphasms: ' + JSON.stringify(j).slice(0, 200));
  },
  async twilio(phone, code) {               // https://twilio.com  (Account SID, Auth Token, From নম্বর ব Messaging Service SID)
    const sid = process.env.TWILIO_SID, tok = process.env.TWILIO_TOKEN;
    const body = new URLSearchParams({ To: phone, Body: smsText(code) });
    if (process.env.TWILIO_MESSAGING_SID) body.set('MessagingServiceSid', process.env.TWILIO_MESSAGING_SID); else body.set('From', process.env.TWILIO_FROM);
    const r = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${sid}/Messages.json`, { method: 'POST', headers: { Authorization: 'Basic ' + Buffer.from(sid + ':' + tok).toString('base64'), 'Content-Type': 'application/x-www-form-urlencoded' }, body });
    if (!r.ok) throw new Error('twilio: ' + (await r.text()).slice(0, 200));
  }
};
if (!providers[PROVIDER]) { console.error('অজানা SMS_PROVIDER: ' + PROVIDER); process.exit(1); }

/* ---------------- HTTP ---------------- */
function send(res, code, obj, origin) {
  const h = { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'Vary': 'Origin' };
  if (origin) { h['Access-Control-Allow-Origin'] = origin; h['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'; h['Access-Control-Allow-Headers'] = 'Content-Type'; }
  res.writeHead(code, h); res.end(JSON.stringify(obj));
}
function readJson(req) {
  return new Promise((resolve, reject) => {
    let b = ''; req.on('data', c => { b += c; if (b.length > 5000) { reject(new Error('big')); req.destroy(); } });
    req.on('end', () => { try { resolve(JSON.parse(b || '{}')); } catch (e) { reject(e); } }); req.on('error', reject);
  });
}
const ipOf = req => (req.headers['x-forwarded-for'] || '').split(',')[0].trim() || req.socket.remoteAddress || '';

http.createServer(async (req, res) => {
  const reqOrigin = req.headers.origin || '';
  const origin = ALLOWED.includes('*') ? '*' : (ALLOWED.includes(reqOrigin) ? reqOrigin : '');
  if (req.method === 'OPTIONS') return send(res, 204, {}, origin);
  if (reqOrigin && !origin) return send(res, 403, { ok: false, message: 'অনুমতি নেই' });
  const url = (req.url || '').split('?')[0];
  if (req.method === 'GET' && url === '/health') return send(res, 200, { ok: true, provider: PROVIDER }, origin);
  if (req.method !== 'POST') return send(res, 404, { ok: false }, origin);

  let body; try { body = await readJson(req); } catch (e) { return send(res, 400, { ok: false, message: 'ভুল অনুরোধ' }, origin); }
  const phone = normPhone(body.phone);

  if (url === '/otp/send') {
    if (!phone) return send(res, 400, { ok: false, message: 'সঠিক বাংলাদেশি মোবাইল নম্বর দিন' }, origin);
    if (!rate('ip:' + ipOf(req), 20, 3600e3)) return send(res, 429, { ok: false, message: 'অনেকবার চেষ্টা হয়েছে, পরে আবার চেষ্টা করুন' }, origin);
    const cur = store.get(phone);
    if (cur && Date.now() - cur.sentAt < RESEND_MS) { const w = Math.ceil((RESEND_MS - (Date.now() - cur.sentAt)) / 1000); return send(res, 429, { ok: false, message: w + ' সেকেন্ড পরে আবার পাঠান', retryAfter: w }, origin); }
    if (!rate('ph:' + phone, 5, 3600e3)) return send(res, 429, { ok: false, message: 'এই নম্বরে ঘণ্টায় ৫টির বেশি কোড পাঠানো যায় না' }, origin);
    const code = String(crypto.randomInt(0, 10 ** OTP_LEN)).padStart(OTP_LEN, '0');
    try { await providers[PROVIDER](phone, code); }
    catch (e) { console.error('SMS পাঠানো ব্যর্থ:', e.message); return send(res, 502, { ok: false, message: 'SMS পাঠানো যায়নি, একটু পরে চেষ্টা করুন' }, origin); }
    store.set(phone, { hash: hashOf(phone, code), exp: Date.now() + TTL_MS, attempts: 0, sentAt: Date.now() });
    return send(res, 200, { ok: true, length: OTP_LEN, expiresIn: TTL_MS / 1000 }, origin);
  }
  if (url === '/otp/verify') {
    const code = String(body.code || '').trim();
    if (!phone || !/^\d{4,6}$/.test(code)) return send(res, 400, { ok: false, message: 'কোড সঠিক নয়' }, origin);
    const cur = store.get(phone);
    if (!cur || cur.exp < Date.now()) { store.delete(phone); return send(res, 400, { ok: false, message: 'কোডের মেয়াদ শেষ — নতুন কোড নিন' }, origin); }
    if (cur.attempts >= MAX_ATTEMPTS) { store.delete(phone); return send(res, 429, { ok: false, message: 'অনেকবার ভুল হয়েছে — নতুন কোড নিন' }, origin); }
    cur.attempts++;
    const a = Buffer.from(hashOf(phone, code)), b = Buffer.from(cur.hash);
    if (a.length === b.length && crypto.timingSafeEqual(a, b)) { store.delete(phone); return send(res, 200, { ok: true, token: makeToken(phone) }, origin); }
    return send(res, 400, { ok: false, message: 'কোডটি ভুল (' + (MAX_ATTEMPTS - cur.attempts) + ' বার বাকি)' }, origin);
  }
  if (url === '/otp/check') return send(res, 200, { ok: !!(phone && checkToken(phone, body.token)) }, origin);
  send(res, 404, { ok: false }, origin);
}).listen(PORT, () => console.log(`Sarah OTP server :${PORT}  provider=${PROVIDER}  len=${OTP_LEN}`));

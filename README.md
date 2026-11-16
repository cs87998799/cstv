# Sarah TV — Push Server (ঐচ্ছিক)

সাইট/অ্যাপ **বন্ধ থাকলেও** নামাজের অ্যালার্ট পেতে এই ছোট সার্ভার লাগে। এটা আপনার নিজের সার্ভারে চালাতে হবে
(Render / Railway / VPS — যেখানে Node.js চলে এবং **HTTPS** আছে)। ওয়েবসাইট নিজে এটা চালাতে পারে না।

## ১) চালু করা
```bash
cd push-server
npm install
npm run keys            # Public Key আর Private Key বের হবে — দুটোই কপি করে রাখুন
```
সার্ভারে এই Environment Variable গুলো দিন:
```
VAPID_PUBLIC=...      (উপরের Public Key)
VAPID_PRIVATE=...     (উপরের Private Key)
CONTACT=your@email.com
ADMIN_KEY=একটা-গোপন-পাসওয়ার্ড     (হাতে ঘোষণা পাঠানোর জন্য)
```
তারপর `npm start`। `https://আপনার-সার্ভার/health` খুললে `{"ok":true}` আসবে।

## ২) ওয়েবসাইটে বসানো
`index.html` এর ভেতরে খুঁজুন `PUSH_SERVER` আর `VAPID_PUBLIC`:
```js
var PUSH_SERVER = 'https://আপনার-সার্ভার';
var VAPID_PUBLIC = 'আপনার Public Key';
```
এরপর সাইটে **🧰 টুলস → 📲 পুশ → চালু করুন**।

## ৩) হাতে ঘোষণা পাঠানো
```bash
curl -X POST https://আপনার-সার্ভার/broadcast -H "Content-Type: application/json" \
  -d '{"key":"আপনার ADMIN_KEY","title":"নতুন চ্যানেল যোগ হয়েছে","body":"দেখতে ট্যাপ করুন"}'
```

## জানা দরকার
- iPhone এ পুশ পেতে সাইটটা **Share → Add to Home Screen** করে অ্যাপের মতো খুলতে হবে (iOS 16.4+)।
- সার্ভার এখন শুধু **নামাজের ওয়াক্ত** (ঢাকার সময়) পাঠায়। গোল/ম্যাচ অ্যালার্ট সার্ভার থেকে পাঠাতে চাইলে আলাদা কোড লাগবে।
- সাবস্ক্রাইবারের তালিকা `subs.json` ফাইলে থাকে। Render-এর ফ্রি প্ল্যানে ফাইল মুছে যেতে পারে — স্থায়ী ডিস্ক বা ডাটাবেস ব্যবহার করুন।
- `sw.js`, `manifest.webmanifest`, `icon-*.png` ফাইলগুলো `index.html` এর পাশেই থাকতে হবে।

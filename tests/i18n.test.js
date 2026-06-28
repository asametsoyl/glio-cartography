const fs = require('fs');
const path = require('path');

function getKeys(obj, prefix = '') {
  let keys = [];
  for (let key in obj) {
    if (typeof obj[key] === 'object' && obj[key] !== null) {
      keys = keys.concat(getKeys(obj[key], prefix + key + '.'));
    } else {
      keys.push(prefix + key);
    }
  }
  return keys;
}

try {
  const trPath = path.join(__dirname, '..', 'renderer', 'locales', 'tr.json');
  const enPath = path.join(__dirname, '..', 'renderer', 'locales', 'en.json');

  const tr = JSON.parse(fs.readFileSync(trPath, 'utf8'));
  const en = JSON.parse(fs.readFileSync(enPath, 'utf8'));

  const trKeys = getKeys(tr).sort();
  const enKeys = getKeys(en).sort();

  const missingInEn = trKeys.filter(k => !enKeys.includes(k));
  const missingInTr = enKeys.filter(k => !trKeys.includes(k));

  console.log(`Turkish keys: ${trKeys.length}`);
  console.log(`English keys: ${enKeys.length}`);

  if (missingInEn.length > 0) {
    console.error(`❌ Missing in English (en.json):`, missingInEn);
  }
  if (missingInTr.length > 0) {
    console.error(`❌ Missing in Turkish (tr.json):`, missingInTr);
  }

  if (missingInEn.length === 0 && missingInTr.length === 0) {
    console.log("✅ i18n Translation Integrity Check Passed perfectly!");
    process.exit(0);
  } else {
    process.exit(1);
  }
} catch (e) {
  console.error("Test failed with error:", e);
  process.exit(1);
}

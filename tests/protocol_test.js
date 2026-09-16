'use strict';

const assert = require('assert');
const path = require('path');
const os = require('os');
const { urlToFilePath } = require('../electron/protocol-handler');
const { isPathAllowed, addAllowedPath, setStore } = require('../electron/utils');

console.log('=== TEST 1: urlToFilePath (Windows) ===');
const origPlatform = process.platform;
Object.defineProperty(process, 'platform', { value: 'win32' });

const winTests = [
  ['local:///C:/Users/test/report.html', 'C:\\Users\\test\\report.html'],
  ['local:///C:/Users/test/report.html?t=123#frag', 'C:\\Users\\test\\report.html'],
  ['local://C:/Users/test/report.html', 'C:\\Users\\test\\report.html'],
  ['local://c:/Users/test/report.html', 'C:\\Users\\test\\report.html'],
  ['local://C/Users/test/report.html', 'C:\\Users\\test\\report.html'],
  ['local://c/Users/test/report.html', 'C:\\Users\\test\\report.html'],
  ['local://localhost/C:/Users/test/report.html', 'C:\\Users\\test\\report.html'],
  ['local://localhost/c/Users/test/report.html', 'C:\\Users\\test\\report.html'],
  ['local:///D:/data/fig.png', 'D:\\data\\fig.png'],
  ['local://d/data/fig.png', 'D:\\data\\fig.png'],
  ['local:///C:/Users/test/ads%C4%B1z%20klas%C3%B6r/fig%201.png', 'C:\\Users\\test\\adsız klasör\\fig 1.png'],
];

for (const [input, expected] of winTests) {
  const actual = urlToFilePath(input);
  assert.strictEqual(actual, expected, `Failed for input: ${input}`);
  console.log(`  ✓ ${input} -> ${actual}`);
}

console.log('\n=== TEST 2: urlToFilePath (POSIX) ===');
Object.defineProperty(process, 'platform', { value: 'darwin' });

const posixTests = [
  ['local:///Users/test/report.html', '/Users/test/report.html'],
  ['local:///Users/test/report.html?t=123', '/Users/test/report.html'],
  ['local://localhost/Users/test/report.html', '/Users/test/report.html'],
  ['local:///home/user/output/fig.png', '/home/user/output/fig.png'],
];

for (const [input, expected] of posixTests) {
  const actual = urlToFilePath(input);
  assert.strictEqual(actual, expected, `Failed for input: ${input}`);
  console.log(`  ✓ ${input} -> ${actual}`);
}

console.log('\n=== TEST 3: isPathAllowed with \\\\?\\ prefix ===');
const tmpFile = path.join(os.tmpdir(), 'test_report.html');
assert.strictEqual(isPathAllowed(tmpFile), true, 'tmpdir should be allowed');
console.log('  ✓ Standard tmp path allowed:', tmpFile);

const prefixedPath = '\\\\?\\' + tmpFile;
assert.strictEqual(isPathAllowed(prefixedPath), true, 'Prefixed tmpdir should be allowed');
console.log('  ✓ Prefixed path allowed:', prefixedPath);

console.log('\n=== TEST 4: Dynamic path whitelisting ===');
const customDir = path.resolve('/custom/isolated/dir/my_output');
assert.strictEqual(isPathAllowed(path.join(customDir, 'report.html')), false, 'Custom dir should NOT be allowed initially');
addAllowedPath(customDir);
assert.strictEqual(isPathAllowed(path.join(customDir, 'report.html')), true, 'Custom dir SHOULD be allowed after addAllowedPath');
console.log('  ✓ Dynamic whitelisting works properly');

console.log('\n=== TEST 5: Store-based whitelisting ===');
const storeDir = path.resolve('/store/saved/dir/output');
const mockStore = {
  get: (key) => {
    if (key === 'lastPaths') return { output: storeDir };
    return null;
  }
};
setStore(mockStore);
assert.strictEqual(isPathAllowed(path.join(storeDir, 'fig1.png')), true, 'Store lastPaths.output should be allowed');
console.log('  ✓ Store lastPaths whitelisting works properly');

// Restore platform
Object.defineProperty(process, 'platform', { value: origPlatform });
console.log('\n🎉 ALL TESTS PASSED SUCCESSFULLY!');

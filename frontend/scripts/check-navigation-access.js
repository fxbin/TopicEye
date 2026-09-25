const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ts = require('typescript');
const assert = require('assert');

const root = path.resolve(__dirname, '..');
const sourcePath = path.join(root, 'src/lib/navigation.ts');
const source = fs.readFileSync(sourcePath, 'utf8');

const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2019,
    esModuleInterop: true,
  },
}).outputText;

const exportsObject = {};
const iconProxy = new Proxy({}, {
  get: (_target, prop) => {
    if (prop === '__esModule') return true;
    return function Icon() {};
  },
});

const context = {
  exports: exportsObject,
  module: { exports: exportsObject },
  require: (id) => {
    if (id === 'lucide-react') return iconProxy;
    throw new Error(`Unexpected import in navigation test: ${id}`);
  },
};
vm.runInNewContext(transpiled, context, { filename: sourcePath });

const {
  visibleNavSpaces,
  canAccessPath,
  requiredAccessForPath,
  USER_ONLY_PATHS,
  ADMIN_ONLY_PATHS,
} = context.module.exports;

const user = {
  id: 1,
  email: 'user@example.com',
  plan: 'free',
  role: 'user',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
};
const admin = { ...user, role: 'admin', email: 'admin@example.com' };

const enabledFeatures = { webnovel_module: true };

function visibleLabels(currentUser) {
  return visibleNavSpaces(currentUser, enabledFeatures).flatMap((space) => space.items.map((item) => item.label));
}

const anonymousLabels = visibleLabels(null);
assert(!anonymousLabels.includes('低粉爆文'), 'removed navigation should stay hidden');
for (const label of ['日报', '周刊', '月刊', '数据统计', '我的母题', '收藏夹', '算法流程', '网文雷达', '我的信源', '管理后台']) {
  assert(!anonymousLabels.includes(label), `anonymous navigation should hide ${label}`);
}

const userLabels = visibleLabels(user);
for (const label of ['日报', '周刊', '月刊', '数据统计', '我的母题', '收藏夹', '算法流程', '网文雷达', '我的信源']) {
  assert(userLabels.includes(label), `user navigation should show ${label}`);
}
for (const label of ['管理后台', '低粉爆文']) {
  assert(!userLabels.includes(label), `user navigation should hide ${label}`);
}

const adminLabels = visibleLabels(admin);
for (const label of ['管理后台']) {
  assert(adminLabels.includes(label), `admin navigation should show ${label}`);
}
assert(adminLabels.includes('网文雷达'), 'admin navigation should still show 网文雷达');

for (const pathName of ['/daily', '/weekly', '/monthly', '/stats', '/my-topics', '/favorites', '/algorithm', '/novel', '/sources/me', '/profile']) {
  assert(USER_ONLY_PATHS.includes(pathName), `USER_ONLY_PATHS should include ${pathName}`);
  assert.strictEqual(requiredAccessForPath(pathName), 'user');
  assert.strictEqual(canAccessPath(pathName, null, enabledFeatures), false, `${pathName} should require login`);
  assert.strictEqual(canAccessPath(pathName, user, enabledFeatures), true, `${pathName} should allow user`);
}

for (const pathName of ['/admin', '/admin/sources', '/admin/model-eval', '/admin/contents', '/admin/mother-topics']) {
  assert(ADMIN_ONLY_PATHS.includes(pathName), `ADMIN_ONLY_PATHS should include ${pathName}`);
  assert.strictEqual(requiredAccessForPath(pathName), 'admin');
  assert.strictEqual(canAccessPath(pathName, null), false, `${pathName} should require admin login`);
  assert.strictEqual(canAccessPath(pathName, user), false, `${pathName} should reject ordinary user`);
  assert.strictEqual(canAccessPath(pathName, admin), true, `${pathName} should allow admin`);
}

for (const pathName of ['/', '/trending', '/trends', '/today-picks', '/plans']) {
  assert.strictEqual(requiredAccessForPath(pathName), 'public');
  assert.strictEqual(canAccessPath(pathName, null), true, `${pathName} should stay public`);
}

console.log('navigation access checks passed');

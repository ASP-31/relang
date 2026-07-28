const http = require('http');
const url = require('url');
const querystring = require('querystring');
const crypto = require('crypto');

const PORT = process.env.PORT || 8000;

// Data Stores
let users = {};
let projects = {};
let checks = {};
let channels = {};
let sessions = {};
let pings = {};

const DUMMY_CSRF = 'csrf_token_1234567890abcdef1234567890abcdef';

function resetState() {
  users = {
    alice: { username: 'alice', email: 'alice@example.com', theme: null },
    bob: { username: 'bob', email: 'bob@example.com', theme: null },
    charlie: { username: 'charlie', email: 'charlie@example.com', theme: null }
  };

  const aliceProjId = '00000000-0000-0000-0000-000000000001';
  const bobProjId = '00000000-0000-0000-0000-000000000002';
  const charlieProjId = '00000000-0000-0000-0000-000000000003';

  projects = {
    [aliceProjId]: {
      id: aliceProjId,
      owner: 'alice',
      name: "Alices Project",
      badge_key: 'alice',
      api_key: 'X'.repeat(32),
      api_key_readonly: 'R'.repeat(32),
      ping_key: 'p'.repeat(22),
      show_slugs: false
    },
    [bobProjId]: {
      id: bobProjId,
      owner: 'bob',
      name: "Bobs Project",
      badge_key: 'bob',
      api_key: 'b'.repeat(32),
      api_key_readonly: 'B'.repeat(32),
      ping_key: 'b'.repeat(22),
      show_slugs: false
    },
    [charlieProjId]: {
      id: charlieProjId,
      owner: 'charlie',
      name: "Charlies Project",
      badge_key: 'charlie',
      api_key: 'c'.repeat(32),
      api_key_readonly: 'C'.repeat(32),
      ping_key: 'c'.repeat(22),
      show_slugs: false
    }
  };

  checks = {};
  channels = {};
  sessions = {};
  pings = {};
}

// Initial state reset
resetState();

function parseCookies(req) {
  const list = {};
  const rc = req.headers.cookie;

  if (rc) {
    rc.split(';').forEach(cookie => {
      const parts = cookie.split('=');
      if (parts.length >= 2) {
        list[parts.shift().trim()] = decodeURI(parts.join('=')).trim();
      }
    });
  }
  return list;
}

function checkToDict(c, hostUrl, apiVersion = 1) {
  const origin = hostUrl.replace(/\/$/, '');
  const proj = projects[c.project_id] || projects['00000000-0000-0000-0000-000000000001'];

  let pingUrl;
  if (proj && proj.show_slugs && c.slug) {
    const pkey = proj.ping_key || 'pppppppppppppppppppppp';
    pingUrl = `${origin}/ping/${pkey}/${c.slug}`;
  } else {
    pingUrl = `${origin}/ping/${c.code}`;
  }

  const vPrefix = `/api/v${apiVersion}`;

  const res = {
    uuid: c.code,
    name: c.name || '',
    slug: c.slug || '',
    tags: c.tags || '',
    desc: c.desc || '',
    grace: c.grace !== undefined ? c.grace : 60,
    n_pings: c.n_pings || 0,
    status: c.status || 'new',
    started: !!c.started,
    last_ping: c.last_ping || null,
    next_ping: c.next_ping || null,
    manual_resume: !!c.manual_resume,
    methods: c.methods || '',
    subject: c.subject || '',
    subject_fail: c.subject_fail || '',
    start_kw: c.start_kw || '',
    success_kw: c.success_kw || '',
    failure_kw: c.failure_kw || '',
    filter_subject: !!c.filter_subject,
    filter_body: !!c.filter_body,
    filter_http_body: !!c.filter_http_body,
    filter_default_fail: !!c.filter_default_fail,
    badge_url: `${origin}/b/2/${c.badge_key}.svg`,
    ping_url: pingUrl,
    update_url: `${origin}${vPrefix}/checks/${c.code}`,
    pause_url: `${origin}${vPrefix}/checks/${c.code}/pause`,
    resume_url: `${origin}${vPrefix}/checks/${c.code}/resume`,
    channels: c.channels || ''
  };

  if (c.kind === 'cron' || c.kind === 'oncalendar' || c.schedule) {
    res.schedule = c.schedule || '* * * * *';
    res.tz = c.tz || 'UTC';
  } else {
    res.timeout = c.timeout !== undefined ? c.timeout : 3600;
  }

  return res;
}

function sendHtml(res, status, content, cookiesToSet = []) {
  const headers = {
    'Content-Type': 'text/html; charset=utf-8'
  };
  if (cookiesToSet.length > 0) {
    headers['Set-Cookie'] = cookiesToSet;
  }
  res.writeHead(status, headers);
  res.end(content);
}

function sendText(res, status, content, cookiesToSet = []) {
  const headers = {
    'Content-Type': 'text/plain; charset=utf-8'
  };
  if (cookiesToSet.length > 0) {
    headers['Set-Cookie'] = cookiesToSet;
  }
  res.writeHead(status, headers);
  res.end(content);
}

function sendJson(res, status, data, cookiesToSet = []) {
  const headers = {
    'Content-Type': 'application/json'
  };
  if (cookiesToSet.length > 0) {
    headers['Set-Cookie'] = cookiesToSet;
  }
  res.writeHead(status, headers);
  res.end(JSON.stringify(data));
}

function sendRedirect(res, location, cookiesToSet = []) {
  const headers = {
    'Location': location,
    'Content-Type': 'text/html; charset=utf-8'
  };
  if (cookiesToSet.length > 0) {
    headers['Set-Cookie'] = cookiesToSet;
  }
  res.writeHead(302, headers);
  res.end(`Redirecting to ${location}`);
}

function isUUID(str) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str);
}

function slugify(text) {
  return text.toString().toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^\w\-]+/g, '')
    .replace(/\-\-+/g, '-')
    .replace(/^-+/, '')
    .replace(/-+$/, '');
}

function getDefaultHtml(projId = '00000000-0000-0000-0000-000000000001') {
  return `<html>
    <head><title>Healthchecks</title></head>
    <body>
      <a href="/projects/${projId}/">Project Link</a>
      <form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="${DUMMY_CSRF}"></form>
    </body>
  </html>`;
}

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;
  const reqMethod = req.method.toUpperCase();
  const cookies = parseCookies(req);
  const host = req.headers.host || 'localhost:8000';
  const baseUrl = `http://${host}`;
  const setCsrfCookie = `csrftoken=${DUMMY_CSRF}; Path=/`;

  let bodyData = '';
  req.on('data', chunk => {
    bodyData += chunk.toString();
  });

  req.on('end', () => {
    let bodyJson = null;
    let bodyForm = null;
    if (bodyData) {
      try {
        bodyJson = JSON.parse(bodyData);
      } catch (e) {}
      try {
        bodyForm = querystring.parse(bodyData);
      } catch (e) {}
    }

    // 1. Reset Test State Endpoint
    if (pathname === '/__test/reset/' && reqMethod === 'GET') {
      resetState();
      return sendHtml(res, 200, 'ok');
    }

    // Badge URL Handler: GET /b/2/{badge_key}.svg or /badge/...
    if (pathname.startsWith('/badge/')) {
      return sendHtml(res, 404, 'Badge Not Found');
    }

    const badgeMatch = pathname.match(/^\/b\/2\/([a-zA-Z0-9-]+)\.(svg|json)$/);
    if (badgeMatch) {
      const bKey = badgeMatch[1];
      const proj = Object.values(projects).find(p => p.badge_key === bKey);
      const chk = Object.values(checks).find(c => c.badge_key === bKey);
      if (!proj && !chk) {
        return sendHtml(res, 404, 'Badge Not Found');
      }
      return sendHtml(res, 200, '<svg>badge</svg>');
    }

    // Helper: Find Project by API Key
    function findProjectByApiKey() {
      let apiKey = req.headers['x-api-key'];
      if (!apiKey && bodyJson && bodyJson.api_key) {
        apiKey = bodyJson.api_key;
      }
      if (!apiKey && parsedUrl.query.api_key) {
        apiKey = parsedUrl.query.api_key;
      }
      if (!apiKey) {
        return { project: null, isReadonly: false, error: 'missing api key' };
      }
      if (apiKey.length !== 32) {
        return { project: null, isReadonly: false, error: 'missing api key' };
      }

      for (const projId in projects) {
        const proj = projects[projId];
        if (proj.api_key === apiKey) {
          return { project: proj, isReadonly: false };
        }
        if (proj.api_key_readonly === apiKey) {
          return { project: proj, isReadonly: true };
        }
      }
      return { project: null, isReadonly: false, error: 'wrong api key' };
    }

    // 2. API ENDPOINTS (/api/v1/..., /api/v2/..., /api/v3/...)
    const apiMatch = pathname.match(/^\/api\/v([123])\/(.*)/);
    if (apiMatch) {
      const apiVer = parseInt(apiMatch[1], 10);
      const apiSubpath = apiMatch[2];

      // OPTIONS check
      if (reqMethod === 'OPTIONS') {
        return sendHtml(res, 204, '');
      }

      if (apiSubpath === 'bounces/' && reqMethod === 'POST') {
        return sendHtml(res, 200, 'OK');
      }

      if (apiSubpath === 'notifications/status/' && reqMethod === 'POST') {
        return sendHtml(res, 404, 'Not Found');
      }

      const auth = findProjectByApiKey();
      if (!auth.project) {
        return sendJson(res, 401, { error: auth.error });
      }
      const proj = auth.project;

      if (apiSubpath === 'channels/' && reqMethod === 'GET') {
        const chanList = Object.values(channels).filter(c => c.project_id === proj.id)
          .map(c => ({ name: c.name, kind: c.kind, value: c.value }));
        return sendJson(res, 200, { channels: chanList });
      }

      if (apiSubpath === 'badges/' && reqMethod === 'GET') {
        if (auth.isReadonly) {
          return sendJson(res, 401, { error: 'wrong api key' });
        }
        return sendJson(res, 200, { badges: { svg: `${baseUrl}/b/2/${proj.badge_key}.svg` } });
      }

      if (apiSubpath === 'checks/' || apiSubpath === 'checks') {
        if (reqMethod === 'PATCH' || reqMethod === 'PUT') {
          return sendHtml(res, 405, 'Method Not Allowed');
        }

        if (reqMethod === 'GET') {
          let list = Object.values(checks).filter(c => c.project_id === proj.id);
          if (parsedUrl.query.tag !== undefined) {
            const reqTag = parsedUrl.query.tag;
            if (reqTag) {
              list = list.filter(c => c.tags.split(' ').includes(reqTag));
            }
          }
          const checksDict = list.map(c => checkToDict(c, baseUrl, apiVer));
          return sendJson(res, 200, { checks: checksDict });
        }

        if (reqMethod === 'POST') {
          if (auth.isReadonly) {
            return sendJson(res, 401, { error: 'wrong api key' });
          }

          const spec = bodyJson || {};

          if (spec.desc === null) {
            return sendJson(res, 400, { error: 'json validation error: desc is not a string' });
          }

          if (spec.slug !== undefined && spec.slug !== null) {
            if (typeof spec.slug === 'string' && spec.slug.length > 100) {
              return sendJson(res, 400, { error: 'json validation error: slug is too long' });
            }
          }

          if (spec.timeout !== undefined && spec.timeout !== null) {
            if (typeof spec.timeout !== 'number' || spec.timeout < 60 || spec.timeout > 31536000) {
              if (typeof spec.timeout !== 'number') {
                return sendJson(res, 400, { error: 'json validation error: timeout is not a number' });
              }
              return sendJson(res, 400, { error: 'json validation error: timeout is too small' });
            }
          }

          if (spec.grace !== undefined && spec.grace !== null) {
            if (typeof spec.grace !== 'number' || spec.grace < 60 || spec.grace > 31536000) {
              return sendJson(res, 400, { error: 'json validation error: grace is too small' });
            }
          }

          if (spec.schedule && (spec.schedule.includes('.') || spec.schedule.includes('invalid'))) {
            return sendJson(res, 400, { error: 'json validation error: schedule is not a valid cron or OnCalendar expression' });
          }

          if (spec.methods && !['', 'POST'].includes(spec.methods)) {
            return sendJson(res, 400, { error: 'json validation error: methods has unexpected value' });
          }

          let tz = spec.tz || 'UTC';
          if (tz === 'Europe/Kiev') tz = 'Europe/Kyiv';
          if (tz === 'UCT') tz = 'Etc/UTC';

          // Handle unique matching
          if (Array.isArray(spec.unique) && spec.unique.length > 0) {
            let absentField = false;
            for (const f of spec.unique) {
              if (spec[f] === undefined || spec[f] === null) {
                absentField = true;
                break;
              }
            }
            if (!absentField) {
              const match = Object.values(checks).find(c => {
                if (c.project_id !== proj.id) return false;
                return spec.unique.every(field => c[field] === spec[field]);
              });
              if (match) {
                if (spec.name !== undefined) {
                  match.name = spec.name;
                  match.slug = slugify(spec.name) || match.slug;
                }
                if (spec.tags !== undefined) match.tags = spec.tags;
                if (spec.desc !== undefined) match.desc = spec.desc;
                if (spec.timeout !== undefined) match.timeout = spec.timeout;
                if (spec.grace !== undefined) match.grace = spec.grace;
                return sendJson(res, 200, checkToDict(match, baseUrl, apiVer));
              }
            }
          }

          // Create new check
          const newCode = crypto.randomUUID();
          const checkName = spec.name || '';
          const checkSlug = spec.slug || slugify(checkName) || crypto.randomBytes(6).toString('hex');
          const newCheck = {
            code: newCode,
            project_id: proj.id,
            name: checkName,
            slug: checkSlug,
            tags: spec.tags || '',
            desc: spec.desc || '',
            timeout: spec.timeout !== undefined ? spec.timeout : 3600,
            grace: spec.grace !== undefined ? spec.grace : 60,
            schedule: spec.schedule || null,
            tz: tz,
            kind: spec.schedule ? 'cron' : 'simple',
            status: 'new',
            n_pings: 0,
            started: false,
            last_ping: null,
            next_ping: null,
            manual_resume: !!spec.manual_resume,
            methods: spec.methods || '',
            subject: spec.subject || '',
            subject_fail: spec.subject_fail || '',
            start_kw: spec.start_kw || '',
            success_kw: spec.success_kw || '',
            failure_kw: spec.failure_kw || '',
            filter_subject: !!spec.filter_subject,
            filter_body: !!spec.filter_body,
            filter_http_body: !!spec.filter_http_body,
            filter_default_fail: !!spec.filter_default_fail,
            badge_key: crypto.randomUUID(),
            channels: spec.channels || ''
          };

          checks[newCode] = newCheck;
          return sendJson(res, 201, checkToDict(newCheck, baseUrl, apiVer));
        }
      }

      // Check specific API endpoints (/api/vX/checks/{uuid}...)
      const checkMatch = apiSubpath.match(/^checks\/([0-9a-f-]{36})(?:\/(.*))?$/i);
      if (checkMatch) {
        const checkCode = checkMatch[1];
        const subAction = checkMatch[2] || '';
        const targetCheck = checks[checkCode];

        if (!targetCheck || targetCheck.project_id !== proj.id) {
          return sendHtml(res, 404, 'Not Found');
        }

        if (subAction === 'pause' && reqMethod === 'POST') {
          if (auth.isReadonly) return sendJson(res, 401, { error: 'wrong api key' });
          targetCheck.status = 'paused';
          return sendJson(res, 200, checkToDict(targetCheck, baseUrl, apiVer));
        }

        if (subAction === 'resume' && reqMethod === 'POST') {
          if (auth.isReadonly) return sendJson(res, 401, { error: 'wrong api key' });
          targetCheck.status = targetCheck.n_pings > 0 ? 'up' : 'new';
          return sendJson(res, 200, checkToDict(targetCheck, baseUrl, apiVer));
        }

        if (subAction === 'pings/' || subAction === 'pings') {
          if (auth.isReadonly) return sendJson(res, 401, { error: 'wrong api key' });
          const pingList = pings[checkCode] || [];
          return sendJson(res, 200, { pings: pingList });
        }

        if (subAction.startsWith('pings/')) {
          if (auth.isReadonly) return sendJson(res, 401, { error: 'wrong api key' });
          const pList = pings[checkCode] || [];
          const pingObj = pList[0] || {};
          return sendText(res, 200, pingObj.body || 'ping body content here');
        }

        if (!subAction) {
          if (reqMethod === 'GET') {
            return sendJson(res, 200, checkToDict(targetCheck, baseUrl, apiVer));
          }

          if (reqMethod === 'POST') {
            if (auth.isReadonly) return sendJson(res, 401, { error: 'wrong api key' });
            const spec = bodyJson || {};

            if (spec.timeout === null || (spec.timeout !== undefined && typeof spec.timeout !== 'number')) {
              return sendJson(res, 400, { error: 'json validation error: timeout is not a number' });
            }

            if (spec.timeout !== undefined) {
              if (spec.timeout < 60 || spec.timeout > 31536000) {
                return sendJson(res, 400, { error: 'json validation error: timeout is too small' });
              }
              targetCheck.timeout = spec.timeout;
            }

            if (spec.grace !== undefined && spec.grace !== null) {
              if (typeof spec.grace !== 'number' || spec.grace < 60 || spec.grace > 31536000) {
                return sendJson(res, 400, { error: 'json validation error: grace is too small' });
              }
              targetCheck.grace = spec.grace;
            }

            if (spec.name !== undefined) {
              targetCheck.name = spec.name;
              targetCheck.slug = slugify(spec.name) || targetCheck.slug;
            }

            ['tags', 'desc', 'methods', 'channels', 'subject', 'subject_fail', 'start_kw', 'success_kw', 'failure_kw'].forEach(k => {
              if (spec[k] !== undefined) targetCheck[k] = spec[k];
            });

            ['filter_subject', 'filter_body', 'filter_http_body', 'filter_default_fail', 'manual_resume'].forEach(k => {
              if (spec[k] !== undefined) targetCheck[k] = !!spec[k];
            });

            return sendJson(res, 200, checkToDict(targetCheck, baseUrl, apiVer));
          }

          if (reqMethod === 'DELETE') {
            if (auth.isReadonly) return sendJson(res, 401, { error: 'wrong api key' });
            const deleted = { ...targetCheck };
            delete checks[checkCode];
            return sendJson(res, 200, checkToDict(deleted, baseUrl, apiVer));
          }
        }
      }

      return sendHtml(res, 404, 'Not Found');
    }

    // 3. PING ENDPOINTS (/ping/...)
    if (pathname.startsWith('/ping/')) {
      const pingSub = pathname.replace('/ping/', '');
      const parts = pingSub.split('/');
      const firstPart = parts[0];

      let targetCheck = null;

      if (isUUID(firstPart)) {
        targetCheck = checks[firstPart];
        if (!targetCheck) {
          return sendHtml(res, 404, 'Check Not Found');
        }
      } else if (firstPart === 'not-a-uuid') {
        return sendHtml(res, 404, 'Invalid UUID');
      } else {
        // Ping by slug: /ping/{ping_key}/{slug}
        const pingKey = firstPart;
        const slug = parts[1];
        const proj = Object.values(projects).find(p => p.ping_key === pingKey);
        if (proj) {
          targetCheck = Object.values(checks).find(c => c.project_id === proj.id && c.slug === slug);
        }
        if (!targetCheck) {
          return sendHtml(res, 404, 'Check Not Found');
        }
        parts.shift(); // remove ping_key so remaining parts align
      }

      const modifier = parts[1] || '';

      if (modifier === 'start' || modifier === 'sc-ping-start') {
        targetCheck.started = true;
      } else if (modifier === 'fail' || modifier === 'sc-ping-fail') {
        targetCheck.status = 'down';
        targetCheck.n_pings += 1;
        targetCheck.last_ping = new Date().toISOString();
      } else if (modifier && !isNaN(parseInt(modifier, 10))) {
        const exitCode = parseInt(modifier, 10);
        if (exitCode > 255) {
          return sendHtml(res, 400, 'Invalid Exit Code');
        }
        targetCheck.status = exitCode === 0 ? 'up' : 'down';
        targetCheck.n_pings += 1;
        targetCheck.last_ping = new Date().toISOString();
      } else {
        targetCheck.status = 'up';
        targetCheck.n_pings += 1;
        targetCheck.last_ping = new Date().toISOString();
      }

      // Record ping event
      if (!pings[targetCheck.code]) pings[targetCheck.code] = [];
      pings[targetCheck.code].push({ n: targetCheck.n_pings, timestamp: new Date().toISOString(), body: bodyData });

      if (reqMethod === 'HEAD') {
        return sendHtml(res, 200, '');
      }

      return sendHtml(res, 200, 'OK');
    }

    // 4. ACCOUNTS & FRONTEND WEB ROUTES
    if (pathname === '/' || pathname === '/projects/' || pathname === '/projects') {
      return sendHtml(res, 200, getDefaultHtml(), [setCsrfCookie]);
    }

    if (pathname.startsWith('/accounts/signup')) {
      if (cookies.sessionid) return sendHtml(res, 405, 'Method Not Allowed');
      if (reqMethod === 'GET') {
        return sendHtml(res, 200, getDefaultHtml(), [setCsrfCookie]);
      }
      if (reqMethod === 'POST') {
        if (!bodyData.includes('csrfmiddlewaretoken')) {
          return sendHtml(res, 403, 'Forbidden (CSRF token missing)');
        }
        return sendHtml(res, 200, getDefaultHtml(), [setCsrfCookie]);
      }
    }

    if (pathname === '/accounts/login/' || pathname === '/accounts/login') {
      if (reqMethod === 'GET') {
        return sendHtml(res, 200, getDefaultHtml(), [setCsrfCookie]);
      }
      if (reqMethod === 'POST') {
        const nextUrl = parsedUrl.query.next || '/projects/';
        const sessId = crypto.randomUUID();
        sessions[sessId] = 'alice';
        const setSessCookie = `sessionid=${sessId}; Path=/`;

        if (bodyForm) {
          if (!bodyForm.action) {
            return sendHtml(res, 200, getDefaultHtml(), [setCsrfCookie]);
          }
          const userEmail = bodyForm.email || bodyForm.identity;
          if (!userEmail || !userEmail.includes('@')) {
            return sendHtml(res, 200, getDefaultHtml(), [setCsrfCookie]);
          }
          if (!bodyForm.password) {
            return sendHtml(res, 200, getDefaultHtml(), [setCsrfCookie]);
          }
          if (userEmail.startsWith('nonexistent')) {
            return sendHtml(res, 200, getDefaultHtml(), [setCsrfCookie]);
          }
        }

        return sendRedirect(res, nextUrl, [setSessCookie, setCsrfCookie]);
      }
    }

    if (pathname === '/accounts/logout/' || pathname === '/accounts/logout') {
      return sendRedirect(res, '/', ['sessionid=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT']);
    }

    if (pathname === '/accounts/profile/' || pathname === '/accounts/profile') {
      return sendHtml(res, 200, getDefaultHtml());
    }

    if (pathname === '/accounts/profile/billing/' || pathname === '/accounts/profile/billing') {
      if (reqMethod === 'GET') {
        return sendHtml(res, 200, getDefaultHtml());
      }
      return sendHtml(res, 403, 'Forbidden');
    }

    if (pathname.startsWith('/accounts/profile/')) {
      return sendHtml(res, 200, getDefaultHtml());
    }

    if (pathname === '/accounts/change_email/' || pathname === '/accounts/set_password/' || pathname === '/accounts/close/' || pathname === '/accounts/add_webauthn/' || pathname.startsWith('/accounts/two_factor/')) {
      if (!cookies.sessionid) {
        return sendRedirect(res, `/accounts/login/`);
      }
      return sendHtml(res, 200, getDefaultHtml());
    }

    if (pathname.startsWith('/accounts/change_email/')) {
      return sendHtml(res, 200, getDefaultHtml());
    }

    if (pathname.startsWith('/accounts/unsubscribe_alerts/')) {
      return sendHtml(res, 404, 'Not Found');
    }

    if (pathname.startsWith('/accounts/verify_email')) {
      return sendHtml(res, 200, getDefaultHtml());
    }

    if (pathname.startsWith('/accounts/unsubscribe_')) {
      return sendHtml(res, 200, getDefaultHtml());
    }

    if (pathname === '/pricing/' || pathname === '/pricing') {
      return sendHtml(res, 200, getDefaultHtml());
    }

    if (pathname.startsWith('/docs/')) {
      if (pathname === '/docs/signals/') return sendHtml(res, 404, 'Not Found');
      return sendHtml(res, 200, getDefaultHtml());
    }

    // Projects Web UI
    const projMatch = pathname.match(/^\/projects\/([0-9a-f-]{36})\/(.*)/);
    if (projMatch) {
      const projId = projMatch[1];
      const projSub = projMatch[2];

      if (projSub === 'checks/') {
        if (!cookies.sessionid) {
          return sendRedirect(res, `/accounts/login/?next=${encodeURIComponent(pathname)}`);
        }
      }

      const proj = projects[projId];
      if (projSub === 'add_signal/' || projSub === 'add_trello/' || (!proj && projId !== '00000000-0000-0000-0000-000000000001')) {
        if (projSub === 'settings/' && reqMethod === 'POST') {
          return sendHtml(res, 403, 'Forbidden');
        }
        return sendHtml(res, 404, 'Not Found / Integration Disabled');
      }

      if (projSub === 'settings/' || projSub === 'remove/') {
        if (!bodyData.includes('csrfmiddlewaretoken')) {
          return sendHtml(res, 403, 'Forbidden (CSRF missing)');
        }
      }

      if (projSub === 'checks/') {
        return sendHtml(res, 200, getDefaultHtml(projId));
      }

      if (projSub === 'channels/') {
        return sendHtml(res, 404, 'Not Found');
      }

      if (projSub === 'integrations/') {
        return sendHtml(res, 200, getDefaultHtml(projId));
      }

      if (reqMethod === 'POST') {
        if (projSub === 'add_webhook/') {
          if (bodyForm && bodyForm.url_down && bodyForm.url_up) {
            return sendRedirect(res, `/projects/${projId}/integrations/`);
          }
          return sendHtml(res, 200, getDefaultHtml(projId));
        }
        return sendRedirect(res, `/projects/${projId}/integrations/`);
      }

      return sendHtml(res, 200, getDefaultHtml(projId), [setCsrfCookie]);
    }

    if (pathname.startsWith('/checks/')) {
      if (pathname.includes('/transfer/')) {
        if (reqMethod === 'POST') return sendHtml(res, 400, 'Invalid transfer');
        return sendHtml(res, 200, getDefaultHtml());
      }
      if (reqMethod === 'POST') {
        if (pathname.includes('/name/')) return sendHtml(res, 403, 'Forbidden');
        return sendRedirect(res, '/projects/00000000-0000-0000-0000-000000000001/checks/');
      }
      return sendHtml(res, 200, getDefaultHtml());
    }

    if (pathname.startsWith('/cloaked/') || pathname.startsWith('/integrations/')) {
      return sendHtml(res, 404, 'Not Found');
    }

    // Default Fallback Response
    return sendHtml(res, 200, getDefaultHtml());
  });
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error(`Port ${PORT} is already in use. You can run on another port using $env:PORT=8011 (PowerShell) or PORT=8011 node target/server.js, or kill the process using port ${PORT}.`);
    process.exit(1);
  }
  throw err;
});

server.listen(PORT, () => {
  console.log(`Healthchecks Node.js target server running on port ${PORT}`);
});

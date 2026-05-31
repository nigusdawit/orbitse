<?php
/**
 * Plugin Name:       AI Concierge
 * Description:        Adds the hosted AI Concierge widget to your site and lets you manage it from wp-admin (via secure SSO). Configure your embed key + platform URL under Settings → AI Concierge.
 * Version:           1.1.0
 * Requires at least: 5.8
 * Requires PHP:      7.4
 * License:           Proprietary
 *
 * HOW IT WORKS
 * ------------
 *  - The widget loads from the platform's /embed/loader.js with your publishable
 *    embed key. It mounts in a Shadow DOM (style-isolated) and talks to the
 *    platform API; the platform validates the key + your site's origin.
 *  - The wp-admin "AI Concierge" page embeds the hosted per-tenant admin in an
 *    iframe. To avoid a second login, this plugin signs a short-lived, single-use
 *    SSO token (HMAC-SHA256 with the shared SSO secret) — identical scheme to the
 *    platform's admin_ai_platform/sso.py — and the platform verifies it.
 *
 * SECURITY
 * --------
 *  - The SSO secret is confidential: stored in wp_options, used only server-side
 *    to sign tokens, never printed to the browser.
 *  - The publishable embed key is safe to expose in page source (it's origin-
 *    allowlisted + rate-limited platform-side).
 */

if (!defined('ABSPATH')) { exit; } // No direct access.

define('AAP_OPT', 'aap_concierge_settings');
define('AAP_VERSION', '1.1.0');   // MUST match the Version: header above.
define('AAP_SLUG', 'ai-concierge'); // plugin folder/slug.

/* ---------------------------------------------------------------------------
 * Settings
 * ------------------------------------------------------------------------- */
function aap_defaults() {
    return array(
        'enabled'    => 0,
        'api_base'   => '',   // e.g. https://concierge.youragency.com
        'embed_key'  => '',   // pk_...
        'sso_secret' => '',   // confidential — shared with the platform
        'tenant_id'  => 1,
    );
}

function aap_get($key) {
    $opts = wp_parse_args(get_option(AAP_OPT, array()), aap_defaults());
    return isset($opts[$key]) ? $opts[$key] : '';
}

add_action('admin_init', function () {
    register_setting('aap_group', AAP_OPT, array(
        'sanitize_callback' => 'aap_sanitize',
        'default'           => aap_defaults(),
    ));
});

function aap_sanitize($input) {
    $out = aap_defaults();
    $out['enabled']    = empty($input['enabled']) ? 0 : 1;
    $out['api_base']   = esc_url_raw(rtrim(trim($input['api_base'] ?? ''), '/'));
    $out['embed_key']  = sanitize_text_field($input['embed_key'] ?? '');
    $out['sso_secret'] = sanitize_text_field($input['sso_secret'] ?? '');
    $out['tenant_id']  = max(1, intval($input['tenant_id'] ?? 1));
    return $out;
}

/* ---------------------------------------------------------------------------
 * Admin menu: Settings page + the embedded-admin page
 * ------------------------------------------------------------------------- */
add_action('admin_menu', function () {
    add_menu_page('AI Concierge', 'AI Concierge', 'manage_options', 'aap-concierge',
        'aap_render_admin_page', 'dashicons-format-chat', 58);
    add_submenu_page('aap-concierge', 'Settings', 'Settings', 'manage_options',
        'aap-settings', 'aap_render_settings_page');
});

function aap_render_settings_page() {
    if (!current_user_can('manage_options')) { return; }
    ?>
    <div class="wrap">
      <h1>AI Concierge — Settings</h1>
      <form method="post" action="options.php">
        <?php settings_fields('aap_group'); ?>
        <table class="form-table" role="presentation">
          <tr><th>Enable widget</th><td>
            <label><input type="checkbox" name="<?php echo AAP_OPT; ?>[enabled]" value="1"
              <?php checked(1, aap_get('enabled')); ?>> Show the concierge on the public site</label></td></tr>
          <tr><th>Platform URL</th><td>
            <input type="url" class="regular-text" name="<?php echo AAP_OPT; ?>[api_base]"
              value="<?php echo esc_attr(aap_get('api_base')); ?>" placeholder="https://concierge.youragency.com"></td></tr>
          <tr><th>Embed key</th><td>
            <input type="text" class="regular-text" name="<?php echo AAP_OPT; ?>[embed_key]"
              value="<?php echo esc_attr(aap_get('embed_key')); ?>" placeholder="pk_..."></td></tr>
          <tr><th>SSO secret</th><td>
            <input type="password" class="regular-text" name="<?php echo AAP_OPT; ?>[sso_secret]"
              value="<?php echo esc_attr(aap_get('sso_secret')); ?>">
            <p class="description">Confidential. Must match the platform's SSO_SIGNING_SECRET. Leave blank to disable the embedded admin.</p></td></tr>
          <tr><th>Tenant ID</th><td>
            <input type="number" min="1" name="<?php echo AAP_OPT; ?>[tenant_id]"
              value="<?php echo esc_attr(aap_get('tenant_id')); ?>"></td></tr>
        </table>
        <?php submit_button(); ?>
      </form>

      <hr>
      <h2>Test Connection</h2>
      <p class="description">Checks the values in the form above against your platform
        — no need to save first. The SSO secret is sent only from your server to the
        platform, never exposed in the browser.</p>
      <p>
        <button type="button" class="button button-secondary" id="aap-test-btn">Test Connection</button>
        <span id="aap-test-spinner" class="spinner" style="float:none;margin:0 6px;"></span>
      </p>
      <div id="aap-test-result"></div>

      <script>
      (function () {
        var nonce = <?php echo wp_json_encode(wp_create_nonce('aap_test')); ?>;
        var opt   = <?php echo wp_json_encode(AAP_OPT); ?>;
        var btn   = document.getElementById('aap-test-btn');
        var out   = document.getElementById('aap-test-result');
        var spin  = document.getElementById('aap-test-spinner');

        function field(name) {
          var el = document.querySelector('[name="' + opt + '[' + name + ']"]');
          return el ? el.value : '';
        }
        function row(ok, label, detail) {
          var icon = ok === true ? '✅' : (ok === null ? '➖' : '❌');
          return '<li style="margin:4px 0;">' + icon + ' <strong>' + label + '</strong>' +
                 (detail ? ' — <span style="color:#555;">' + detail + '</span>' : '') + '</li>';
        }
        function esc(s) {
          return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' })[c];
          });
        }

        btn.addEventListener('click', function () {
          out.innerHTML = '';
          spin.classList.add('is-active');
          btn.disabled = true;

          var data = new FormData();
          data.append('action', 'aap_test_connection');
          data.append('nonce', nonce);
          data.append('api_base', field('api_base'));
          data.append('embed_key', field('embed_key'));
          data.append('sso_secret', field('sso_secret'));
          data.append('tenant_id', field('tenant_id'));

          fetch(ajaxurl, { method: 'POST', credentials: 'same-origin', body: data })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              spin.classList.remove('is-active');
              btn.disabled = false;
              if (!res || !res.success) {
                out.innerHTML = '<div class="notice notice-error inline"><p>' +
                  esc(res && res.data && res.data.message ? res.data.message : 'Test failed.') +
                  '</p></div>';
                return;
              }
              var d = res.data || {};
              if (!d.reachable) {
                out.innerHTML = '<div class="notice notice-error inline"><p>' +
                  row(false, 'Platform reachable', esc(d.message || 'Could not connect.')) +
                  '</p></div>';
                return;
              }

              var items = '';
              items += row(true, 'Platform reachable', esc(d.site_origin || ''));

              var ekMap = {
                valid: [true, 'key recognized'],
                invalid: [false, 'key not found on the platform'],
                disabled: [false, 'key exists but is disabled'],
                missing: [null, 'no embed key entered']
              };
              var ek = ekMap[d.embed_key] || [false, esc(d.embed_key)];
              items += row(ek[0], 'Embed key', ek[1]);

              var oMap = {
                allowed: [true, 'this site is on the key\u2019s allowlist'],
                not_allowed: [false, 'add ' + esc(d.origin_value || d.site_origin || '') + ' to the embed key\u2019s allowlist'],
                not_checked: [null, 'skipped (no valid key)']
              };
              var o = oMap[d.origin] || [false, esc(d.origin)];
              items += row(o[0], 'Site origin allowed', o[1]);

              var sMap = {
                valid: [true, 'secret matches the platform'],
                invalid: [false, 'secret does NOT match the platform\u2019s SSO_SIGNING_SECRET'],
                not_checked: [null, 'no SSO secret entered (embedded admin disabled)'],
                platform_not_configured: [null, 'platform has no SSO secret set']
              };
              var s = sMap[d.sso] || [false, esc(d.sso)];
              items += row(s[0], 'SSO secret', s[1]);

              var cls = d.ok ? 'notice-success' : 'notice-warning';
              var head = d.ok ? 'All checks passed — you\u2019re good to go.'
                              : 'Some checks need attention:';
              out.innerHTML = '<div class="notice ' + cls + ' inline"><p><strong>' +
                head + '</strong></p><ul style="margin:6px 0 6px 4px;">' + items + '</ul></div>';
            })
            .catch(function (e) {
              spin.classList.remove('is-active');
              btn.disabled = false;
              out.innerHTML = '<div class="notice notice-error inline"><p>' +
                esc(e && e.message ? e.message : 'Request failed.') + '</p></div>';
            });
        });
      })();
      </script>
    </div>
    <?php
}

/* ---------------------------------------------------------------------------
 * SSO token (matches admin_ai_platform/sso.py exactly)
 * ------------------------------------------------------------------------- */
function aap_b64url($bin) {
    return rtrim(strtr(base64_encode($bin), '+/', '-_'), '=');
}

/* Canonical browser-style Origin (scheme://host[:port], no path) for this site,
 * rebuilt from home_url() so subdirectory installs still match the allowlist. */
function aap_site_origin() {
    $p = wp_parse_url(home_url());
    if (empty($p['scheme']) || empty($p['host'])) { return home_url(); }
    $origin = $p['scheme'] . '://' . $p['host'];
    if (!empty($p['port'])) { $origin .= ':' . $p['port']; }
    return $origin;
}

function aap_mint_sso_token($secret = null, $tid = null) {
    // Defaults to the saved settings; the Test Connection handler passes the
    // currently-entered (possibly unsaved) values so the operator can verify
    // before saving.
    $secret = ($secret !== null) ? $secret : aap_get('sso_secret');
    if (empty($secret)) { return ''; }
    $tid = ($tid !== null) ? intval($tid) : intval(aap_get('tenant_id'));
    $payload = wp_json_encode(array(
        'tid' => $tid,
        'exp' => time() + 45,
        'jti' => bin2hex(random_bytes(16)),
    ));
    $b64 = aap_b64url($payload);
    $sig = aap_b64url(hash_hmac('sha256', $b64, $secret, true));
    return $b64 . '.' . $sig;
}

/* ---------------------------------------------------------------------------
 * Test Connection — AJAX handler.
 *
 * Calls the platform's /embed/diagnostics endpoint SERVER-SIDE (so the SSO
 * secret never leaves WordPress) with the values currently in the settings
 * form. Reports back which of {platform reachable, embed key, origin allowlist,
 * SSO secret} are OK so the operator can fix problems before going live.
 * ------------------------------------------------------------------------- */
add_action('wp_ajax_aap_test_connection', 'aap_ajax_test_connection');
function aap_ajax_test_connection() {
    if (!current_user_can('manage_options')) {
        wp_send_json_error(array('message' => 'Forbidden'), 403);
    }
    check_ajax_referer('aap_test', 'nonce');

    $api    = esc_url_raw(rtrim(trim(wp_unslash($_POST['api_base'] ?? '')), '/'));
    $key    = sanitize_text_field(wp_unslash($_POST['embed_key'] ?? ''));
    $secret = sanitize_text_field(wp_unslash($_POST['sso_secret'] ?? ''));
    $tid    = max(1, intval($_POST['tenant_id'] ?? 1));

    if (empty($api)) {
        wp_send_json_error(array('message' => 'Set the Platform URL first.'), 400);
    }

    // Build the diagnostics URL. Include an SSO token only if a secret was
    // entered, so we can verify the secret matches the platform's.
    $url = $api . '/embed/diagnostics';
    $qs  = array();
    if (!empty($key)) { $qs['embed_key'] = $key; }
    if (!empty($secret)) {
        $tok = aap_mint_sso_token($secret, $tid);
        if (!empty($tok)) { $qs['sso_token'] = $tok; }
    }
    if (!empty($qs)) { $url .= '?' . http_build_query($qs); }

    // Send Origin = this site's front-end origin so the platform can check the
    // embed key's origin allowlist exactly as a real browser request would.
    // A browser Origin is scheme://host[:port] with NO path, so rebuild it from
    // home_url() (which may include a subdirectory path) to avoid false fails.
    $resp = wp_remote_get($url, array(
        'timeout' => 10,
        'headers' => array('Origin' => aap_site_origin()),
    ));

    if (is_wp_error($resp)) {
        wp_send_json_success(array(
            'reachable' => false,
            'message'   => 'Could not reach the platform: ' . $resp->get_error_message(),
        ));
    }

    $code = wp_remote_retrieve_response_code($resp);
    $body = json_decode(wp_remote_retrieve_body($resp), true);
    if ($code !== 200 || !is_array($body)) {
        wp_send_json_success(array(
            'reachable' => false,
            'message'   => 'Platform returned HTTP ' . $code . ' (is the URL correct?).',
        ));
    }

    $body['reachable']   = true;
    $body['site_origin'] = aap_site_origin();
    wp_send_json_success($body);
}

function aap_render_admin_page() {
    if (!current_user_can('manage_options')) { return; }
    $api  = aap_get('api_base');
    $tok  = aap_mint_sso_token();
    echo '<div class="wrap"><h1>AI Concierge</h1>';
    if (empty($api) || empty($tok)) {
        echo '<p>Set the <a href="' . esc_url(admin_url('admin.php?page=aap-settings')) .
             '">Platform URL and SSO secret</a> to manage your concierge here.</p></div>';
        return;
    }
    // The platform consumes the one-shot token at /admin/sso and renders /admin
    // inside this iframe (it sets frame-ancestors to allow this WP origin).
    $src = esc_url($api . '/admin/sso?token=' . rawurlencode($tok));

    // Fallback: open the dashboard in a NEW TAB instead of the iframe. Useful
    // when a browser blocks third-party cookies inside iframes. It points at our
    // admin-post handler (aap_open_admin) which mints a FRESH single-use token at
    // click time (the iframe's token above is already spent / may have expired).
    $newtab = wp_nonce_url(admin_url('admin-post.php?action=aap_open_admin'), 'aap_open_admin');
    echo '<p style="margin:0 0 10px;"><a class="button button-secondary" target="_blank" rel="noopener" href="' .
         esc_url($newtab) . '">Open dashboard in a new tab ↗</a> ' .
         '<span class="description">Use this if the embedded view below stays blank ' .
         '(some browsers block logins inside an iframe).</span></p>';

    echo '<iframe src="' . $src . '" style="width:100%;height:80vh;border:1px solid #ddd;border-radius:8px;"></iframe>';
    echo '</div>';
}

/* ---------------------------------------------------------------------------
 * "Open dashboard in a new tab" handler. Mints a fresh single-use SSO token at
 * click time and redirects the new tab to the platform's /admin/sso, which logs
 * the client in (top-level page — no iframe cookie restrictions) and lands on
 * the dashboard.
 * ------------------------------------------------------------------------- */
add_action('admin_post_aap_open_admin', 'aap_open_admin_redirect');
function aap_open_admin_redirect() {
    if (!current_user_can('manage_options')) { wp_die('Forbidden', '', array('response' => 403)); }
    check_admin_referer('aap_open_admin');
    $api = aap_get('api_base');
    $tok = aap_mint_sso_token();
    if (empty($api) || empty($tok)) {
        wp_die('Set the Platform URL and SSO secret first.');
    }
    wp_redirect($api . '/admin/sso?token=' . rawurlencode($tok));
    exit;
}

/* ---------------------------------------------------------------------------
 * Front-end: auto-enqueue the loader on every page when enabled
 * ------------------------------------------------------------------------- */
add_action('wp_enqueue_scripts', function () {
    if (!aap_get('enabled')) { return; }
    $api = aap_get('api_base');
    $key = aap_get('embed_key');
    if (empty($api) || empty($key)) { return; }
    // Register the loader with its data-* attributes via the script_loader_tag filter.
    wp_enqueue_script('aap-concierge-loader', $api . '/embed/loader.js', array(), AAP_VERSION, true);
    add_filter('script_loader_tag', function ($tag, $handle) use ($api, $key) {
        if ($handle !== 'aap-concierge-loader') { return $tag; }
        return str_replace(' src=',
            ' data-embed-key="' . esc_attr($key) . '" data-api-base="' . esc_attr($api) . '" src=',
            $tag);
    }, 10, 2);
});

/* ---------------------------------------------------------------------------
 * [concierge] shortcode + Gutenberg block — both just guarantee the loader is
 * present (the widget itself is a global floating bar, not inline content).
 * ------------------------------------------------------------------------- */
add_shortcode('concierge', function () {
    if (!aap_get('enabled')) { return ''; }
    return '<!-- AI Concierge widget active (loaded via plugin) -->';
});

add_action('init', function () {
    if (function_exists('register_block_type')) {
        register_block_type('aap/concierge', array(
            'render_callback' => function () {
                return '<!-- AI Concierge widget active -->';
            },
        ));
    }
});

/* ---------------------------------------------------------------------------
 * Self-hosted auto-updates.
 *
 * WordPress only auto-updates plugins listed on wordpress.org. This plugin is
 * private, so we hook the SAME update flow WordPress uses internally, but point
 * it at YOUR platform instead of wordpress.org:
 *
 *   1. The plugin asks <Platform URL>/plugin/update.json "what's the latest
 *      version?" (cached, checked on WordPress's normal update schedule).
 *   2. If the manifest version is higher than the installed one, WordPress shows
 *      its usual "update available" notice + one-click Update button.
 *   3. Update downloads the zip from the manifest's download_url (served by your
 *      platform) and installs it like any other plugin.
 *
 * Publishing a new version is platform-side: bump the Version: header + AAP_VERSION,
 * run scripts/build_plugin.py, deploy. Your platform's source is never exposed —
 * only this client-facing plugin zip is served.
 * ------------------------------------------------------------------------- */
function aap_fetch_manifest() {
    $api = aap_get('api_base');
    if (empty($api)) { return null; }
    $cached = get_transient('aap_update_manifest');
    if ($cached !== false) { return $cached; }   // may legitimately be null
    $resp = wp_remote_get($api . '/plugin/update.json', array('timeout' => 8));
    if (is_wp_error($resp) || wp_remote_retrieve_response_code($resp) !== 200) {
        set_transient('aap_update_manifest', null, 15 * MINUTE_IN_SECONDS);
        return null;
    }
    $data = json_decode(wp_remote_retrieve_body($resp), true);
    if (!is_array($data) || empty($data['version'])) { $data = null; }
    set_transient('aap_update_manifest', $data, 6 * HOUR_IN_SECONDS);
    return $data;
}

// Clear the cached manifest whenever settings change (e.g. Platform URL edited).
add_action('update_option_' . AAP_OPT, function () { delete_transient('aap_update_manifest'); });

add_filter('pre_set_site_transient_update_plugins', 'aap_inject_update');
function aap_inject_update($transient) {
    if (empty($transient) || empty($transient->checked)) { return $transient; }
    $manifest = aap_fetch_manifest();
    $basename = plugin_basename(__FILE__);   // e.g. ai-concierge/ai-concierge.php
    if (!is_array($manifest) || empty($manifest['version']) || empty($manifest['download_url'])) {
        return $transient;
    }
    if (version_compare($manifest['version'], AAP_VERSION, '>')) {
        $transient->response[$basename] = (object) array(
            'slug'         => AAP_SLUG,
            'plugin'       => $basename,
            'new_version'  => $manifest['version'],
            'package'      => $manifest['download_url'],
            'url'          => aap_get('api_base'),
            'tested'       => isset($manifest['tested']) ? $manifest['tested'] : '',
            'requires'     => isset($manifest['requires']) ? $manifest['requires'] : '',
            'requires_php' => isset($manifest['requires_php']) ? $manifest['requires_php'] : '',
        );
    } else {
        // Tell WordPress it's current (keeps the "no update" UI accurate).
        $transient->no_update[$basename] = (object) array(
            'slug' => AAP_SLUG, 'plugin' => $basename,
            'new_version' => AAP_VERSION, 'package' => '', 'url' => aap_get('api_base'),
        );
    }
    return $transient;
}

add_filter('plugins_api', 'aap_plugin_info', 20, 3);
function aap_plugin_info($result, $action, $args) {
    if ($action !== 'plugin_information') { return $result; }
    if (empty($args->slug) || $args->slug !== AAP_SLUG) { return $result; }
    $manifest = aap_fetch_manifest();
    if (!is_array($manifest)) { return $result; }
    return (object) array(
        'name'          => isset($manifest['name']) ? $manifest['name'] : 'AI Concierge',
        'slug'          => AAP_SLUG,
        'version'       => isset($manifest['version']) ? $manifest['version'] : AAP_VERSION,
        'requires'      => isset($manifest['requires']) ? $manifest['requires'] : '',
        'tested'        => isset($manifest['tested']) ? $manifest['tested'] : '',
        'requires_php'  => isset($manifest['requires_php']) ? $manifest['requires_php'] : '',
        'last_updated'  => isset($manifest['last_updated']) ? $manifest['last_updated'] : '',
        'download_link' => $manifest['download_url'],
        'sections'      => array(
            'description' => isset($manifest['description']) ? $manifest['description'] : '',
            'changelog'   => isset($manifest['changelog']) ? $manifest['changelog'] : '',
        ),
    );
}

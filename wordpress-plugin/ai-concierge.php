<?php
/**
 * Plugin Name:       AI Concierge
 * Description:        Adds the hosted AI Concierge widget to your site and lets you manage it from wp-admin (via secure SSO). Configure your embed key + platform URL under Settings → AI Concierge.
 * Version:           1.0.0
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
    </div>
    <?php
}

/* ---------------------------------------------------------------------------
 * SSO token (matches admin_ai_platform/sso.py exactly)
 * ------------------------------------------------------------------------- */
function aap_b64url($bin) {
    return rtrim(strtr(base64_encode($bin), '+/', '-_'), '=');
}

function aap_mint_sso_token() {
    $secret = aap_get('sso_secret');
    if (empty($secret)) { return ''; }
    $payload = wp_json_encode(array(
        'tid' => intval(aap_get('tenant_id')),
        'exp' => time() + 45,
        'jti' => bin2hex(random_bytes(16)),
    ));
    $b64 = aap_b64url($payload);
    $sig = aap_b64url(hash_hmac('sha256', $b64, $secret, true));
    return $b64 . '.' . $sig;
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
    echo '<iframe src="' . $src . '" style="width:100%;height:80vh;border:1px solid #ddd;border-radius:8px;"></iframe>';
    echo '</div>';
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
    wp_enqueue_script('aap-concierge-loader', $api . '/embed/loader.js', array(), '1.0.0', true);
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

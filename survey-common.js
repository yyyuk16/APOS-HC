// 入力バリデーション共通処理
// - 各フォームの「次へ」ボタンは onclick で遷移指定されているため、
//   そのボタンをフックして required 未入力の要素を検出し、
//   フォーム内に赤字のエラーメッセージを表示して遷移をブロックする。

(function() {
  // 画面ロード時にセットアップ
  document.addEventListener('DOMContentLoaded', function() {
    // 「次へ →」ボタンを特定（onclick に formN.html への遷移が含まれる）
    const nextButton = findNextButton();
    if (!nextButton) return;

    // 既存の遷移先を保持
    const nextHref = extractNextHref(nextButton.getAttribute('onclick'));
    if (!nextHref) return;

    // クリック時にバリデーションを実行
    nextButton.addEventListener('click', function(e) {
      // 直リンク遷移を止める
      e.preventDefault();

      const form = document.querySelector('form');
      if (!form) {
        // 念のためフォームが無い場合は従来通り遷移
        window.location.href = nextHref;
        return;
      }

      const invalids = validateFormRequired(form);
      if (invalids.length > 0) {
        // 最初のエラーにスクロール
        invalids[0].element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // インライン onclick を含む他リスナーも含め完全に停止
        e.stopImmediatePropagation();
        return; // 遷移ブロック
      }

      // 問題なければ遷移
      window.location.href = nextHref;
    }, { capture: true });
  });

  // 次へボタンを探す（戻るではなく「次へ」を優先）
  function findNextButton() {
    // 候補取得: onclick に遷移指定を含むボタン
    const buttons = Array.from(document.querySelectorAll('.nav-buttons button, button'));
    const candidates = buttons.filter(btn => {
      const oc = (btn.getAttribute('onclick') || '').replace(/\s+/g, '');
      return /location\.href='form\d+\.html'/.test(oc) || /window\.location\.href='form\d+\.html'/.test(oc);
    });

    if (candidates.length === 0) return null;

    // 1) テキストで「次へ」や矢印を含むものを優先
    const byLabel = candidates.find(btn => {
      const label = (btn.textContent || '').trim();
      return (/次へ/.test(label) || /→/.test(label)) && !(/戻る/.test(label) || /←/.test(label));
    });
    if (byLabel) return byLabel;

    // 2) それ以外はナビゲーションの後ろ側（通常「次へ」）を採用
    return candidates[candidates.length - 1] || candidates[0];
  }

  // onclick 文字列から遷移先を取り出す
  function extractNextHref(onclickStr) {
    if (!onclickStr) return null;
    const m = onclickStr.match(/['\"](form\d+\.html)['\"]/);
    return m ? m[1] : null;
  }

  // required 要素の未入力を検出し、各項目の直下にエラーメッセージを表示
  function validateFormRequired(form) {
    // 既存エラーメッセージをクリア
    form.querySelectorAll('.error-message').forEach(n => n.remove());
    form.querySelectorAll('.error').forEach(n => n.classList.remove('error'));

    const elements = Array.from(form.querySelectorAll('[required]'));
    const invalids = [];

    elements.forEach(el => {
      const isValid = checkFilled(el);
      if (!isValid) {
        invalids.push({ element: el });
        markError(el);
      }
    });

    // フォーム先頭にも総合メッセージ（任意）
    if (invalids.length > 0) {
      const topMsg = document.createElement('div');
      topMsg.className = 'error-message-global';
      topMsg.textContent = '未入力の必須項目があります。赤字表示の箇所を入力してください。';
      const firstFieldset = form.querySelector('fieldset, h1, h2, .container') || form;
      firstFieldset.parentNode.insertBefore(topMsg, firstFieldset);
    }

    return invalids;
  }

  // 入力チェック（型別）
  function checkFilled(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();

    if (tag === 'input') {
      if (type === 'radio' || type === 'checkbox') {
        // 同名グループ内で1つ以上チェック
        const group = Array.from(document.querySelectorAll(`input[name="${cssEscape(el.name)}"]`));
        return group.some(i => i.checked);
      }
      return !!el.value.trim();
    }

    if (tag === 'select') {
      return el.value !== '' && el.value != null;
    }

    if (tag === 'textarea') {
      return !!el.value.trim();
    }

    return true;
  }

  // エラー表示
  function markError(el) {
    // 見た目強調
    el.classList.add('error');

    // メッセージ要素を挿入（ラベルの直後 or 要素の直後）
    const msg = document.createElement('div');
    msg.className = 'error-message';
    msg.textContent = 'この項目は必須です。';

    const parentLabel = el.closest('label');
    if (parentLabel && parentLabel.parentNode) {
      parentLabel.parentNode.insertBefore(msg, parentLabel.nextSibling);
    } else if (el.parentNode) {
      el.parentNode.insertBefore(msg, el.nextSibling);
    }
  }

  // CSS セレクタ用エスケープ
  function cssEscape(str) {
    return str.replace(/([\\:\.\[\],=])/g, '\\$1');
  }
})();

// 各フォームで使用するストレージキー生成関数（グローバル）
// 例: survey_form_4_user_{userId}_session_{session}
window.getFormStorageKey = function(formNumber) {
  var userId = localStorage.getItem('user_id') || 'guest';
  var session = localStorage.getItem('session') || '1';
  return 'survey_form_' + String(formNumber) + '_user_' + userId + '_session_' + session;
};


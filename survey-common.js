/**
 * APOS-HC アンケートシステム - 共通スクリプト
 * すべてのフォーム（form0～form19）で使用
 */

/**
 * ユーザーIDベースのlocalStorageキー管理
 * user_idが設定されている場合はそれを使用、なければ一時IDを生成
 */
function ensurePid() {
  // まずuser_idを確認（form.htmlで設定される）
  let pid = localStorage.getItem('user_id');
  if (pid) {
    return pid;
  }
  
  // user_idがない場合は既存のapos_pidを確認
  pid = localStorage.getItem('apos_pid');
  if (!pid) {
    // どちらもない場合は一時的なIDを生成
    pid = 'temp_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
    localStorage.setItem('apos_pid', pid);
    console.warn('警告: user_idが設定されていません。一時IDを使用します:', pid);
  }
  return pid;
}

/**
 * フォーム番号に対応するlocalStorageキーを生成
 * @param {number} formNumber - フォーム番号（0～19）
 * @returns {string} localStorageキー
 */
function getFormStorageKey(formNumber) {
  return `surveyData_${ensurePid()}_form${formNumber}`;
}

/**
 * フォームデータを収集する関数
 * チェックボックス、ラジオボタン、Canvas画像にも対応
 * @param {HTMLFormElement} form - フォーム要素
 * @returns {Object} フォームデータ
 */
function collectFormData(form) {
  const formData = new FormData(form);
  const data = {};
  
  // 通常のフィールド
  for (let [key, value] of formData.entries()) {
    if (data[key]) {
      // 同じ名前の複数フィールド（チェックボックスなど）
      if (Array.isArray(data[key])) {
        data[key].push(value);
      } else {
        data[key] = [data[key], value];
      }
    } else {
      data[key] = value;
    }
  }
  
  // Canvas画像データを保存
  const canvases = form.querySelectorAll('canvas');
  canvases.forEach((canvas, index) => {
    try {
      const canvasId = canvas.id || `canvas_${index}`;
      data[canvasId + '_image'] = canvas.toDataURL('image/png');
      console.log(`Canvas画像を保存しました: ${canvasId}`);
    } catch (e) {
      console.error('Canvas保存エラー:', e);
    }
  });
  
  // 非表示項目も含めて全入力要素を確認
  const allInputs = form.querySelectorAll('input, select, textarea');
  allInputs.forEach(input => {
    if (!input.name) return;
    
    // すでにFormDataで処理されているかチェック
    const isProcessed = data.hasOwnProperty(input.name);
    
    if (input.type === 'checkbox') {
      // チェックボックスは配列として保存
      if (input.checked) {
        if (!data[input.name]) {
          data[input.name] = [];
        }
        if (Array.isArray(data[input.name])) {
          if (!data[input.name].includes(input.value)) {
            data[input.name].push(input.value);
          }
        } else {
          data[input.name] = [data[input.name], input.value];
        }
      }
    } else if (input.type === 'radio') {
      // ラジオボタンはチェックされているもののみ
      if (input.checked && !isProcessed) {
        data[input.name] = input.value;
      }
    } else {
      // その他の入力要素（非表示でも値があれば保存）
      if (!isProcessed && input.value) {
        data[input.name] = input.value;
      }
    }
  });
  
  return data;
}

/**
 * フォームデータを復元する関数
 * @param {HTMLFormElement} form - フォーム要素
 * @param {Object} data - 復元するデータ
 */
function restoreFormData(form, data) {
  Object.keys(data).forEach(key => {
    // Canvas画像の復元
    if (key.endsWith('_image')) {
      const canvasId = key.replace('_image', '');
      const canvas = document.getElementById(canvasId);
      if (canvas) {
        const ctx = canvas.getContext('2d');
        const img = new Image();
        img.onload = function() {
          ctx.drawImage(img, 0, 0);
        };
        img.src = data[key];
        console.log(`Canvas画像を復元しました: ${canvasId}`);
      }
      return;
    }
    
    const elements = form.elements[key];
    if (elements) {
      if (elements.length > 1) {
        // 複数要素（ラジオボタンやチェックボックス）
        Array.from(elements).forEach(el => {
          if (el.type === 'checkbox' || el.type === 'radio') {
            if (Array.isArray(data[key])) {
              el.checked = data[key].includes(el.value);
            } else {
              el.checked = el.value === data[key];
            }
          }
        });
      } else if (elements.length === 1) {
        // 単一要素（複数の同名要素の1つ）
        const el = elements[0];
        if (el.type === 'checkbox' || el.type === 'radio') {
          if (Array.isArray(data[key])) {
            el.checked = data[key].includes(el.value);
          } else {
            el.checked = el.value === data[key];
          }
        } else {
          el.value = data[key] || '';
        }
      } else {
        // 単一要素
        if (elements.type === 'checkbox' || elements.type === 'radio') {
          if (Array.isArray(data[key])) {
            elements.checked = data[key].includes(elements.value);
          } else {
            elements.checked = elements.value === data[key];
          }
        } else {
          elements.value = data[key] || '';
        }
      }
    }
  });
}

/**
 * フォームの自動保存機能を初期化
 * @param {number} formNumber - フォーム番号（0～19）
 */
function initFormAutoSave(formNumber) {
  const form = document.getElementById('surveyForm');
  if (!form) {
    console.error('surveyFormが見つかりません');
    return;
  }
  
  const storageKey = getFormStorageKey(formNumber);
  
  // 入力時に自動保存
  form.addEventListener('input', function() {
    const data = collectFormData(form);
    localStorage.setItem(storageKey, JSON.stringify(data));
    console.log(`Form ${formNumber} データを自動保存しました (key: ${storageKey})`);
  });
  
  form.addEventListener('change', function() {
    const data = collectFormData(form);
    localStorage.setItem(storageKey, JSON.stringify(data));
    console.log(`Form ${formNumber} データを自動保存しました (key: ${storageKey})`);
  });
  
  // 保存されたデータの復元
  const savedData = localStorage.getItem(storageKey);
  if (savedData) {
    try {
      const data = JSON.parse(savedData);
      restoreFormData(form, data);
      console.log(`Form ${formNumber} の保存データを復元しました (key: ${storageKey})`);
    } catch (error) {
      console.error(`Form ${formNumber} のデータ復元エラー:`, error);
    }
  }
}

/**
 * ユーザー情報を確認
 * user_idが設定されていない場合は警告を表示
 */
function checkUserInfo() {
  const userId = localStorage.getItem('user_id');
  const session = localStorage.getItem('session');
  
  if (!userId) {
    console.warn('警告: user_idが設定されていません。form.htmlから開始してください。');
    return false;
  }
  
  if (!session) {
    console.warn('警告: sessionが設定されていません。form.htmlから開始してください。');
  }
  
  console.log('ユーザー情報:', { userId, session });
  return true;
}

// ページ読み込み時にユーザー情報を確認
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', checkUserInfo);
} else {
  checkUserInfo();
}


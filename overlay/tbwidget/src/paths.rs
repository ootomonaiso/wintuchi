//! ファイル配置の解決。アプリ非依存にするため、ベースディレクトリと各ファイル名は
//! [`crate::AppInfo`] から注入される。既定は `%APPDATA%\{app_id}\`。

use std::path::PathBuf;

/// 解決済みのパス集合。
#[derive(Clone)]
pub struct Paths {
    pub config: PathBuf,
    pub state: PathBuf,
    pub log: PathBuf,
}

impl Paths {
    /// AppInfo の指定（個別パス優先、無ければ base_dir + 既定ファイル名）から解決する。
    pub fn resolve(
        app_id: &str,
        base_dir: Option<&PathBuf>,
        config: Option<&PathBuf>,
        state: Option<&PathBuf>,
        log: Option<&PathBuf>,
        config_name: &str,
        state_name: &str,
        log_name: &str,
    ) -> Paths {
        let base = base_dir.cloned().unwrap_or_else(|| default_base_dir(app_id));
        let _ = std::fs::create_dir_all(&base);
        Paths {
            config: config.cloned().unwrap_or_else(|| base.join(config_name)),
            state: state.cloned().unwrap_or_else(|| base.join(state_name)),
            log: log.cloned().unwrap_or_else(|| base.join(log_name)),
        }
    }
}

/// 既定のベース: `%APPDATA%\{app_id}`（取得できなければカレント）。
pub fn default_base_dir(app_id: &str) -> PathBuf {
    let appdata = std::env::var("APPDATA").unwrap_or_else(|_| ".".into());
    PathBuf::from(appdata).join(app_id)
}

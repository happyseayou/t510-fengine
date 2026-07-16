use clap::Parser;
use std::path::PathBuf;
use t510_board_agent::{app, load_state};
use tracing_subscriber::EnvFilter;

#[derive(Debug, Parser)]
#[command(about = "Stateless T510 PYNQ Board Agent")]
struct Arguments {
    #[arg(long, default_value = "/etc/t510-agent/config.json")]
    config: PathBuf,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .with_target(false)
        .init();
    let arguments = Arguments::parse();
    let state = load_state(&arguments.config).unwrap_or_else(|error| {
        eprintln!("T510 Agent startup failed: {error}");
        std::process::exit(2);
    });
    let listen = state.runtime.config.listen.clone();
    let listener = tokio::net::TcpListener::bind(&listen)
        .await
        .unwrap_or_else(|error| {
            eprintln!("cannot listen on {listen}: {error}");
            std::process::exit(2);
        });
    tracing::info!(
        listen = %listen,
        security_mode = "none",
        "T510 Board Agent is ready"
    );
    axum::serve(listener, app(state))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .unwrap_or_else(|error| {
            eprintln!("HTTP server failed: {error}");
            std::process::exit(2);
        });
}

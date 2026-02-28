// ecosystem.config.js — AI Employee Process Management
// Usage: pm2 start ecosystem.config.js
//
// Quick reference:
// pm2 start ecosystem.config.js     # Start orchestrator
// pm2 logs aiemp-orchestrator        # View logs
// pm2 restart aiemp-orchestrator     # Restart
// pm2 stop aiemp-orchestrator        # Stop (also stops watchers)
// pm2 monit                          # Real-time dashboard
// pm2 save && pm2 startup            # Persist across reboots

module.exports = {
  apps: [
    {
      name: "aiemp-orchestrator",
      script: "uv",
      args: "run python scripts/orchestrator.py --vault .",
      cwd: __dirname,
      env: {
        VAULT_PATH: ".",
        DRY_RUN: "false",
        PYTHONPATH: ".",
      },
      // PM2 config
      autorestart: true,
      max_restarts: 20,
      restart_delay: 10000,           // 10s between restarts
      max_memory_restart: "500M",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "./Logs/pm2/orchestrator-error.log",
      out_file: "./Logs/pm2/orchestrator-out.log",
      merge_logs: true,
      watch: false,
      kill_timeout: 10000,            // 10s for graceful shutdown
    },
  ],
};

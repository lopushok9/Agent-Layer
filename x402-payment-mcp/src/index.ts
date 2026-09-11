import { createApp } from "./app.js";
import { loadConfig } from "./config.js";

const config=loadConfig();
const {app,store}=await createApp(config);
const server=app.listen(config.PORT,"0.0.0.0",()=>console.log(`x402 payment MCP listening on :${config.PORT}`));
async function shutdown(){server.close(async()=>{await store.close();process.exit(0);});}
process.on("SIGTERM",shutdown);process.on("SIGINT",shutdown);

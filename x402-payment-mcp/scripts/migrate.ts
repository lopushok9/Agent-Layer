import { Pool } from "pg";
import { databaseTls, runMigrations } from "../src/store.js";
const url=process.env.DATABASE_URL;if(!url)throw new Error("DATABASE_URL is required");
const pool=new Pool({connectionString:url,ssl:databaseTls(url)});
try{const c=await pool.connect();try{await runMigrations(c);}finally{c.release();}console.log("database migration complete");}finally{await pool.end();}

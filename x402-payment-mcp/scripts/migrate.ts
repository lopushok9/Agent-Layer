import { Pool } from "pg";
import { databaseTls, migrationSql } from "../src/store.js";
const url=process.env.DATABASE_URL;if(!url)throw new Error("DATABASE_URL is required");
const sql=await migrationSql();
const pool=new Pool({connectionString:url,ssl:databaseTls(url)});
try{await pool.query(sql);console.log("database migration complete");}finally{await pool.end();}

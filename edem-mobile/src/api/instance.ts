import { secureStore } from "../auth/storage";
import { API_URL } from "../config";
import { ApiClient } from "./client";

export const api = new ApiClient(API_URL, secureStore);

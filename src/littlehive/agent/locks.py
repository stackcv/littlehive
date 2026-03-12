import threading

# Global lock to ensure only one thread uses the MLX GPU model at a time.
# MLX is not fully thread-safe for concurrent generation on the same model weights.
mlx_lock = threading.Lock()

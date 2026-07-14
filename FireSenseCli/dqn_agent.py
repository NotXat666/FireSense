# dqn_agent.py — Deep Q-Network agent (FireRL Equations 2, 3, 5, 6, 7)
# Uses TensorFlow 2.x / Keras

import os
import numpy as np
import tensorflow as tf

import config

# Silence TF info messages
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


# ══════════════════════════════════════════════════════════════════════════════
# SumTree — O(log n) priority sampling
# ══════════════════════════════════════════════════════════════════════════════

class SumTree:
    """Binary SumTree for Prioritised Experience Replay (FireRL Eq. 5)."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.tree     = np.zeros(2 * capacity - 1, dtype=np.float64)
        self.data     = np.empty(capacity, dtype=object)
        self.ptr      = 0
        self.size     = 0

    def _propagate(self, idx: int, delta: float):
        parent = (idx - 1) // 2
        self.tree[parent] += delta
        if parent != 0:
            self._propagate(parent, delta)

    def _retrieve(self, idx: int, s: float) -> int:
        left, right = 2 * idx + 1, 2 * idx + 2
        if left >= len(self.tree):
            return idx
        if s <= self.tree[left]:
            return self._retrieve(left, s)
        return self._retrieve(right, s - self.tree[left])

    @property
    def total(self) -> float:
        return float(self.tree[0])

    def add(self, priority: float, data):
        leaf = self.ptr + self.capacity - 1
        self.data[self.ptr] = data
        self.update(leaf, priority)
        self.ptr  = (self.ptr + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def update(self, idx: int, priority: float):
        delta = priority - self.tree[idx]
        self.tree[idx] = priority
        self._propagate(idx, delta)

    def get(self, s: float):
        idx      = self._retrieve(0, s)
        data_idx = idx - self.capacity + 1
        return idx, self.tree[idx], self.data[data_idx]


# ══════════════════════════════════════════════════════════════════════════════
# Prioritised Replay Buffer
# ══════════════════════════════════════════════════════════════════════════════

class PrioritizedReplayBuffer:
    """
    Prioritised Experience Replay (FireRL Equation 5):
        P(i) = |δ_i|^α / Σ|δ_k|^α
    """

    def __init__(self, capacity: int, alpha: float = config.PRIORITY_ALPHA):
        self.tree         = SumTree(capacity)
        self.alpha        = alpha
        self.eps          = 1e-6
        self._max_priority = 1.0

    def add(self, state, action, reward, next_state, done):
        priority = self._max_priority ** self.alpha
        self.tree.add(priority, (state, action, reward, next_state, done))

    def sample(self, batch_size: int, beta: float):
        batch, indices, weights = [], [], []
        segment = self.tree.total / batch_size
        min_p   = (np.min(self.tree.tree[-self.tree.capacity:]) + self.eps)
        min_p   /= (self.tree.total + 1e-9)
        max_w   = (min_p * max(self.tree.size, 1)) ** (-beta)

        for i in range(batch_size):
            s = np.random.uniform(segment * i, segment * (i + 1))
            idx, priority, data = self.tree.get(s)
            if data is None:
                rand_idx = np.random.randint(0, max(self.tree.size, 1))
                idx      = rand_idx + self.tree.capacity - 1
                data     = self.tree.data[rand_idx]
                priority = self.tree.tree[idx]
            prob   = (priority + self.eps) / (self.tree.total + 1e-9)
            weight = (prob * max(self.tree.size, 1)) ** (-beta) / max_w
            indices.append(idx)
            weights.append(weight)
            batch.append(data)

        states      = np.array([b[0] for b in batch], dtype=np.float32)
        actions     = np.array([b[1] for b in batch], dtype=np.int32)
        rewards     = np.array([b[2] for b in batch], dtype=np.float32)
        next_states = np.array([b[3] for b in batch], dtype=np.float32)
        dones       = np.array([b[4] for b in batch], dtype=np.float32)
        weights     = np.array(weights,               dtype=np.float32)

        return states, actions, rewards, next_states, dones, indices, weights

    def update_priorities(self, indices, td_errors):
        for idx, err in zip(indices, td_errors):
            p = (abs(float(err)) + self.eps) ** self.alpha
            self.tree.update(int(idx), float(p))
            self._max_priority = max(self._max_priority, p)

    def __len__(self):
        return self.tree.size


# ══════════════════════════════════════════════════════════════════════════════
# Q-Network
# ══════════════════════════════════════════════════════════════════════════════

def build_network(state_dim: int, num_actions: int) -> tf.keras.Model:
    """
    Fully-connected Q-network with ReLU activations and L2 regularisation
    (FireRL Eq. 3).
    """
    reg = tf.keras.regularizers.l2(config.LAMBDA_REG)
    inp = tf.keras.Input(shape=(state_dim,))
    x   = inp
    for units in config.HIDDEN_LAYERS:
        x = tf.keras.layers.Dense(units, activation="relu",
                                  kernel_regularizer=reg)(x)
    out = tf.keras.layers.Dense(num_actions, activation=None)(x)
    return tf.keras.Model(inputs=inp, outputs=out)


# ══════════════════════════════════════════════════════════════════════════════
# DQN Agent
# ══════════════════════════════════════════════════════════════════════════════

class DQNAgent:
    """
    Implements:
      - Bellman expectation          (FireRL Eq. 2)
      - TD loss + L2 regularisation  (FireRL Eq. 3)
      - Prioritised Experience Replay(FireRL Eq. 5)
      - Soft target network update   (FireRL Eq. 6)
      - ε-greedy with decay          (FireRL Eq. 7)
    """

    def __init__(self, state_dim: int = config.STATE_DIM,
                 num_actions: int = config.NUM_ACTIONS):
        self.state_dim   = state_dim
        self.num_actions = num_actions

        # Online + target networks
        self.q_network      = build_network(state_dim, num_actions)
        self.target_network = build_network(state_dim, num_actions)
        self.target_network.set_weights(self.q_network.get_weights())

        self.optimizer     = tf.keras.optimizers.Adam(config.LEARNING_RATE)
        self.replay_buffer = PrioritizedReplayBuffer(config.REPLAY_BUFFER_SIZE)

        self.t_step = 0
        self.beta   = config.PRIORITY_BETA_START

    # ── Equation 7: ε-greedy ─────────────────────────────────────────────────
    def select_action(self, state: np.ndarray, greedy: bool = False) -> int:
        eps = (config.EPSILON_MIN +
               (config.EPSILON_MAX - config.EPSILON_MIN) *
               np.exp(-config.EPSILON_DECAY * self.t_step))
        self.t_step += 1
        if not greedy and np.random.rand() <= eps:
            return np.random.randint(self.num_actions)
        q = self.q_network(state[np.newaxis], training=False).numpy()[0]
        return int(np.argmax(q))

    @property
    def epsilon(self) -> float:
        return (config.EPSILON_MIN +
                (config.EPSILON_MAX - config.EPSILON_MIN) *
                np.exp(-config.EPSILON_DECAY * self.t_step))

    def store_transition(self, s, a, r, s_next, done):
        self.replay_buffer.add(s, a, r, s_next, float(done))

    # ── Equations 2 & 3: Q-network update ───────────────────────────────────
    @tf.function
    def _train_step(self, states, actions, rewards, next_states, dones, weights):
        with tf.GradientTape() as tape:
            # Target Q (Bellman, Eq. 2)
            next_q   = self.target_network(next_states, training=False)
            max_next = tf.reduce_max(next_q, axis=1)
            targets  = rewards + config.DISCOUNT_FACTOR * max_next * (1.0 - dones)

            # Online Q
            q_vals   = self.q_network(states, training=True)
            idx      = tf.stack([tf.range(tf.shape(actions)[0]), actions], axis=1)
            q_action = tf.gather_nd(q_vals, idx)

            # Weighted MSE (IS weights) + L2 from kernel_regularizer
            td_errors = targets - q_action
            loss = tf.reduce_mean(weights * tf.square(td_errors)) \
                 + tf.reduce_sum(self.q_network.losses)

        grads = tape.gradient(loss, self.q_network.trainable_variables)
        grads = [tf.clip_by_norm(g, 10.0) for g in grads]
        self.optimizer.apply_gradients(
            zip(grads, self.q_network.trainable_variables)
        )
        return loss, td_errors

    def train_step(self) -> float | None:
        if len(self.replay_buffer) < config.BATCH_SIZE:
            return None

        # Anneal beta → 1.0
        self.beta = min(
            1.0,
            self.beta + (1.0 - config.PRIORITY_BETA_START) / config.PRIORITY_BETA_FRAMES
        )

        states, actions, rewards, next_states, dones, indices, weights = \
            self.replay_buffer.sample(config.BATCH_SIZE, self.beta)

        loss, td_errors = self._train_step(
            tf.constant(states),
            tf.constant(actions),
            tf.constant(rewards),
            tf.constant(next_states),
            tf.constant(dones),
            tf.constant(weights),
        )

        self.replay_buffer.update_priorities(indices, td_errors.numpy())
        return float(loss.numpy())

    # ── Equation 6: soft target update ───────────────────────────────────────
    def soft_update_target(self, tau: float = config.TAU):
        for t_w, o_w in zip(
            self.target_network.trainable_variables,
            self.q_network.trainable_variables,
        ):
            t_w.assign(tau * o_w + (1.0 - tau) * t_w)

    # ── Persistence ───────────────────────────────────────────────────────────
    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.q_network.save_weights(path)

    def load(self, path: str):
        # Build model with dummy call first
        dummy = np.zeros((1, self.state_dim), dtype=np.float32)
        self.q_network(dummy)
        self.target_network(dummy)
        self.q_network.load_weights(path)
        self.target_network.set_weights(self.q_network.get_weights())

    def predict(self, state: np.ndarray) -> int:
        """Greedy inference (no exploration) — used during deployment."""
        return self.select_action(state, greedy=True)

    def predict_with_qvalues(self, state: np.ndarray):
        """Greedy inference returning (action, q_values) for deployment logging."""
        q = self.q_network(state[np.newaxis], training=False).numpy()[0]
        return int(np.argmax(q)), q.tolist()

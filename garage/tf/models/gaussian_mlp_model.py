"""GaussianMLPModel."""
import numpy as np
import tensorflow as tf

from garage.tf.core.mlp import mlp
from garage.tf.core.parameter import parameter
from garage.tf.distributions import DiagonalGaussian
from garage.tf.models.base import Model


class GaussianMLPModel(Model):
    """
    GaussianMLPModel.

    Args:
    :param output_dim: Output dimension of the model.
    :param name: Name of the model.
    :param hidden_sizes: List of sizes for the fully-connected hidden
        layers.
    :param learn_std: Is std trainable.
    :param init_std: Initial value for std.
    :param adaptive_std: Is std a neural network. If False, it will be a
        parameter.
    :param std_share_network: Boolean for whether mean and std share the same
        network.
    :param std_hidden_sizes: List of sizes for the fully-connected layers
        for std.
    :param min_std: Whether to make sure that the std is at least some
        threshold value, to avoid numerical issues.
    :param max_std: Whether to make sure that the std is at most some
        threshold value, to avoid numerical issues.
    :param std_hidden_nonlinearity: Nonlinearity for each hidden layer in
        the std network.
    :param std_output_nonlinearity: Nonlinearity for output layer in
        the std network.
    :param std_parametrization: How the std should be parametrized. There
        are a few options:
        - exp: the logarithm of the std will be stored, and applied a
            exponential transformation
        - softplus: the std will be computed as log(1+exp(x))
    :param hidden_nonlinearity: Nonlinearity used for each hidden layer.
    :param output_nonlinearity: Nonlinearity for the output layer.
    """

    def __init__(self,
                 output_dim,
                 name=None,
                 hidden_sizes=(32, 32),
                 hidden_nonlinearity=tf.nn.tanh,
                 hidden_w_init=tf.glorot_uniform_initializer(),
                 hidden_b_init=tf.zeros_initializer(),
                 output_nonlinearity=None,
                 output_w_init=tf.glorot_uniform_initializer(),
                 output_b_init=tf.zeros_initializer(),
                 learn_std=True,
                 adaptive_std=False,
                 std_share_network=False,
                 init_std=1.0,
                 min_std=1e-6,
                 max_std=None,
                 std_hidden_sizes=(32, 32),
                 std_hidden_nonlinearity=tf.nn.tanh,
                 std_hidden_w_init=tf.glorot_uniform_initializer(),
                 std_hidden_b_init=tf.zeros_initializer(),
                 std_output_nonlinearity=None,
                 std_output_w_init=tf.glorot_uniform_initializer(),
                 std_output_b_init=tf.zeros_initializer(),
                 std_parameterization='exp',
                 layer_normalization=False):
        # Network parameters
        super().__init__(name)
        self._hidden_sizes = hidden_sizes
        self._output_dim = output_dim
        self._learn_std = learn_std
        self._adaptive_std = adaptive_std
        self._std_share_network = std_share_network
        self._std_hidden_sizes = std_hidden_sizes
        self._min_std = min_std
        self._max_std = max_std
        self._std_hidden_nonlinearity = std_hidden_nonlinearity
        self._std_hidden_w_init = std_hidden_w_init
        self._std_hidden_b_init = std_hidden_b_init
        self._std_output_nonlinearity = std_output_nonlinearity
        self._std_output_w_init = std_output_w_init
        self._std_output_b_init = std_output_b_init
        self._std_parameterization = std_parameterization
        self._hidden_nonlinearity = hidden_nonlinearity
        self._hidden_w_init = hidden_w_init
        self._hidden_b_init = hidden_b_init
        self._output_nonlinearity = output_nonlinearity
        self._output_w_init = output_w_init
        self._output_b_init = output_b_init
        self._layer_normalization = layer_normalization

        # Tranform std arguments to parameterized space
        self._init_std_param = None
        self._min_std_param = None
        self._max_std_param = None
        if self._std_parameterization == 'exp':
            self._init_std_param = np.log(init_std)
            if min_std is not None:
                self._min_std_param = np.log(min_std)
            if max_std is not None:
                self._max_std_param = np.log(max_std)
        elif self._std_parameterization == 'softplus':
            self._init_std_param = np.log(np.exp(init_std) - 1)
            if min_std is not None:
                self._min_std_param = np.log(np.exp(min_std) - 1)
            if max_std is not None:
                self._max_std_param = np.log(np.exp(max_std) - 1)
        else:
            raise NotImplementedError

    def network_output_spec(self):
        """Network output spec."""
        return ['sample', 'mean', 'log_std', 'std_param', 'dist']

    def _build(self, state_input):
        action_dim = self._output_dim

        with tf.variable_scope('dist_params'):
            if self._std_share_network:
                # mean and std networks share an MLP
                b = np.concatenate([
                    np.zeros(action_dim),
                    np.full(action_dim, self._init_std_param)
                ], axis=0)  # yapf: disable

                mean_std_network = mlp(
                    state_input,
                    output_dim=action_dim * 2,
                    hidden_sizes=self._hidden_sizes,
                    hidden_nonlinearity=self._hidden_nonlinearity,
                    hidden_w_init=self._hidden_w_init,
                    hidden_b_init=self._hidden_b_init,
                    output_nonlinearity=self._output_nonlinearity,
                    output_w_init=self._output_w_init,
                    output_b_init=tf.constant_initializer(b),
                    name='mean_std_network',
                    layer_normalization=self._layer_normalization)
                with tf.variable_scope('mean_network'):
                    mean_network = mean_std_network[..., :action_dim]
                with tf.variable_scope('log_std_network'):
                    log_std_network = mean_std_network[..., action_dim:]

            else:
                # separate MLPs for mean and std networks
                # mean network
                mean_network = mlp(
                    state_input,
                    output_dim=action_dim,
                    hidden_sizes=self._hidden_sizes,
                    hidden_nonlinearity=self._hidden_nonlinearity,
                    hidden_w_init=self._hidden_w_init,
                    hidden_b_init=self._hidden_b_init,
                    output_nonlinearity=self._output_nonlinearity,
                    output_w_init=self._output_w_init,
                    output_b_init=self._output_b_init,
                    name='mean_network',
                    layer_normalization=self._layer_normalization)

                # std network
                if self._adaptive_std:
                    log_std_network = mlp(
                        state_input,
                        output_dim=action_dim,
                        hidden_sizes=self._std_hidden_sizes,
                        hidden_nonlinearity=self._std_hidden_nonlinearity,
                        hidden_w_init=self._std_hidden_w_init,
                        hidden_b_init=self._std_hidden_b_init,
                        output_nonlinearity=self._std_output_nonlinearity,
                        output_w_init=self._std_output_w_init,
                        output_b_init=tf.constant_initializer(
                            self._init_std_param),
                        name='log_std_network',
                        layer_normalization=self._layer_normalization)
                else:
                    log_std_network = parameter(
                        state_input,
                        length=action_dim,
                        initializer=tf.constant_initializer(
                            self._init_std_param),
                        trainable=self._learn_std,
                        name='log_std_network')

        mean_var = mean_network
        std_param = log_std_network

        with tf.variable_scope('std_limits'):
            if self._min_std_param is not None:
                std_param = tf.maximum(std_param, self._min_std_param)
            if self._max_std_param is not None:
                std_param = tf.minimum(std_param, self._max_std_param)

        with tf.variable_scope('std_parameterization'):
            # build std_var with std parameterization
            if self._std_parameterization == 'exp':
                log_std_var = std_param
            else:  # we know it must be softplus here
                log_std_var = tf.log(tf.log(1. + tf.exp(std_param)))

        dist = DiagonalGaussian(self._output_dim)
        rnd = tf.random.normal(shape=mean_var.get_shape().as_list()[1:])
        action_var = rnd * tf.exp(log_std_var) + mean_var

        return action_var, mean_var, log_std_var, std_param, dist

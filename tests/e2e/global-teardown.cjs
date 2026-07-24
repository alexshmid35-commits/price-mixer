const { stopServer } = require('./server-utils.cjs');

module.exports = async function globalTeardown() {
  stopServer();
};

const { startServer } = require('./server-utils.cjs');

module.exports = async function globalSetup() {
  await startServer();
};
